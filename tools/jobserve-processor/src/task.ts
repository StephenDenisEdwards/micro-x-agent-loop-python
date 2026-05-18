import { z } from "zod";
import type { Clients } from "./tools.js";
import { gmailSearch, gmailRead, browserNavigate, browserSnapshot, browserWaitFor, fsRead } from "./tools.js";
import { writeFile, appendFile } from "../../_runtime/src/utils.js";
import { createMessage } from "../../_runtime/src/llm.js";

export const SERVERS = ["google", "playwright", "filesystem"];
export const TOOL_NAME = "jobserve-processor";
export const TOOL_DESCRIPTION = "Processes JobServe job alert emails, retrieves full job specs from JobServe pages, and produces a ranked markdown report.";

export const TOOL_INPUT_SCHEMA = {};

interface Profile {
  hours_back: number;
  output_dir: string;
  max_jobs: number;
  cv_path: string;
  gmail_search_query: string;
  jobserve_url_patterns: string[];
}

interface JobRecord {
  title: string;
  location: string;
  rate: string;
  duration: string;
  employmentBusiness: string;
  contact: string;
  posted: string;
  link: string;
  specMarkdown: string;
  retrieved: boolean;
  errorReason?: string;
  score: number;
  scoreReason: string;
  emailDate: string;
  emailSubject: string;
}

export async function handleTool(
  _input: Record<string, never>,
  clients: Clients,
  profile: Record<string, unknown>,
  _config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const p = profile as unknown as Profile;
  const hoursBack = p.hours_back ?? 24;
  const outputDir = p.output_dir ?? ".";
  const maxJobs = p.max_jobs ?? 50;
  const cvPath = p.cv_path ?? "";
  const gmailQuery = p.gmail_search_query ?? "from:jobsbyemail@apps.jobserve.com";
  const urlPatterns: string[] = p.jobserve_url_patterns ?? ["jobserve.com"];

  const daysBack = Math.max(1, Math.ceil(hoursBack / 24));
  const searchQuery = `${gmailQuery} newer_than:${daysBack}d`;
  console.error(`[jobserve-processor] Searching Gmail: ${searchQuery}`);

  let emails: Array<Record<string, string>>;
  try {
    emails = await gmailSearch(clients, searchQuery, 50);
  } catch (err) {
    return { error: `Gmail search failed: ${String(err)}` };
  }

  if (!emails || emails.length === 0) {
    return { message: "No JobServe emails found in the specified time window.", jobs_processed: 0 };
  }
  console.error(`[jobserve-processor] Found ${emails.length} emails`);

  let cvContent = "";
  try {
    const raw = await fsRead(clients, cvPath);
    if (!raw) throw new Error("CV file returned empty content");
    cvContent = raw;
  } catch (err) {
    return { error: `Cannot read CV file at ${cvPath}: ${String(err)}` };
  }

  const allJobs: JobRecord[] = [];
  let reportDate = new Date().toISOString().slice(0, 10);

  for (const emailMeta of emails) {
    if (allJobs.length >= maxJobs) break;
    const messageId = emailMeta["id"] ?? emailMeta["messageId"];
    if (!messageId) continue;

    let emailData: Record<string, string> | null;
    try {
      emailData = await gmailRead(clients, messageId);
    } catch (err) {
      console.error(`[jobserve-processor] Failed to read email ${messageId}: ${err}`);
      continue;
    }
    if (!emailData) continue;

    const emailDate = parseEmailDate(emailData["date"] ?? "");
    if (emailDate) reportDate = emailDate;
    const rawSubject = emailData["subject"] ?? "";
    const emailSubject = simplifyEmailSubject(rawSubject);

    const body = emailData["body"] ?? "";
    const links = extractJobserveLinks(body, urlPatterns);
    console.error(`[jobserve-processor] Email ${messageId}: found ${links.length} job links`);

    for (const link of links) {
      if (allJobs.length >= maxJobs) break;
      const job = await retrieveJobSpec(clients, link, emailDate ?? reportDate, emailSubject);
      if (job) allJobs.push(job);
    }
  }

  if (allJobs.length === 0) {
    return { message: "No job links found in emails.", jobs_processed: 0 };
  }

  console.error(`[jobserve-processor] Scoring ${allJobs.length} jobs against CV`);
  for (const job of allJobs) {
    const { score, reason } = await scoreJob(job, cvContent);
    job.score = score;
    job.scoreReason = reason;
  }

  const outputPath = `${outputDir}/${reportDate}-js-content-codegened.md`;
  const reportContent = buildReport(allJobs, reportDate);

  await writeFile(outputPath, reportContent, {});
  console.error(`[jobserve-processor] Report written to ${outputPath}`);

  return {
    jobs_processed: allJobs.length,
    output_file: outputPath,
    top_score: allJobs[0]?.score ?? 0,
    report_date: reportDate,
  };
}

function parseEmailDate(dateStr: string): string | null {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return null;
    return d.toISOString().slice(0, 10);
  } catch {
    return null;
  }
}

function extractJobserveLinks(body: string, patterns: string[]): string[] {
  const urlRegex = /https?:\/\/[^\s\]'"<>)]+/g;
  const found = body.match(urlRegex) ?? [];
  const unique = [...new Set(found)];
  return unique.filter((url) => {
    const lc = url.toLowerCase();
    if (!patterns.some((pat) => lc.includes(pat.toLowerCase()))) return false;
    // Only accept JobServe listing-page URLs (W<hash>.jsjob), not search/category pages.
    return lc.includes(".jsjob");
  });
}

function simplifyEmailSubject(subject: string): string {
  // JobServe "Daily Jobs By Email" subjects look like:
  //   "Daily Jobs By Email — AI - Only" or "Daily JobsByEmail: AI"
  // Strip leading "Daily Jobs By Email" prefix so the saved-search name stands out.
  const cleaned = subject
    .replace(/^Daily Jobs?\s*By\s*Email[\s:\-—]*/i, "")
    .trim();
  return cleaned || subject || "Unknown source";
}

async function retrieveJobSpec(
  clients: Clients,
  link: string,
  emailDate: string,
  emailSubject: string,
): Promise<JobRecord | null> {
  console.error(`[jobserve-processor] Retrieving job: ${link}`);

  const baseJob: JobRecord = {
    title: "Unknown",
    location: "",
    rate: "",
    duration: "",
    employmentBusiness: "",
    contact: "",
    posted: "",
    link,
    specMarkdown: "",
    retrieved: false,
    score: 0,
    scoreReason: "",
    emailDate,
    emailSubject,
  };

  try {
    // Navigate to the job link
    const navResult = await browserNavigate(clients, link);
    console.error(`[jobserve-processor] Navigation result:`, JSON.stringify(navResult).slice(0, 200));
    
    await browserWaitFor(clients, { time: 3 });

    const snapshot = await browserSnapshot(clients);
    const snapshotStr = typeof snapshot === "string"
      ? snapshot
      : JSON.stringify(snapshot, null, 2);

    if (!snapshotStr || snapshotStr.length < 100) {
      baseJob.errorReason = "Empty or minimal page content returned";
      return baseJob;
    }

    const parsed = parseSnapshotToJobRecord(snapshotStr, link);
    return { ...baseJob, ...parsed, retrieved: true, link, emailDate, emailSubject };
  } catch (err) {
    console.error(`[jobserve-processor] Failed to retrieve ${link}: ${err}`);
    baseJob.errorReason = String(err);
    return baseJob;
  }
}

type MetaField = "location" | "rate" | "duration" | "employmentBusiness" | "contact" | "posted";

const META_LABELS: Record<string, MetaField> = {
  "location": "location",
  "rate": "rate",
  "salary": "rate",
  "pay rate": "rate",
  "duration": "duration",
  "contract length": "duration",
  "employment agency": "employmentBusiness",
  "employment business": "employmentBusiness",
  "employer": "employmentBusiness",
  "company": "employmentBusiness",
  "client": "employmentBusiness",
  "contact": "contact",
  "recruiter": "contact",
  "posted date": "posted",
  "date posted": "posted",
};

const PREFERRED_POSTED_LABEL = "posted date";

const NAV_CHROME = new Set([
  "skip to content", "home", "job search", "job seekers", "employers",
  "recruiters", "listings", "help", "sign in/register", "apply", "jobserve",
]);

const TITLE_SKIP_PREFIXES = /^(posted|contact|location|rate|salary|duration|industry|reference|permalink|start date|date posted|employment|applicants must|mobile site|jobserve|skip to|sign in|register|home|job search|job seekers|employers|recruiters|listings|help|apply)\b/i;

function extractMetadataPairs(lines: string[]): Partial<Record<MetaField, string>> {
  const out: Partial<Record<MetaField, string>> = {};
  for (let i = 0; i < lines.length - 1; i++) {
    const labelRaw = lines[i].trim();
    const valueRaw = lines[i + 1].trim();
    if (!labelRaw || !valueRaw) continue;
    const label = labelRaw.replace(/:$/, "").toLowerCase();
    const field = META_LABELS[label];
    if (!field) continue;
    if (META_LABELS[valueRaw.replace(/:$/, "").toLowerCase()]) continue;
    const existing = out[field];
    if (existing && field !== "posted") continue;
    if (existing && field === "posted" && label !== PREFERRED_POSTED_LABEL) continue;
    out[field] = valueRaw;
  }
  return out;
}

function findJobTitle(lines: string[]): string | null {
  for (const line of lines) {
    const t = line.trim();
    if (t.length < 10 || t.length > 200) continue;
    if (NAV_CHROME.has(t.toLowerCase())) continue;
    if (/^[+\d]/.test(t)) continue;
    if (/^https?:\/\//i.test(t)) continue;
    if (!/^[A-Z]/.test(t)) continue;
    if (t.endsWith(":")) continue;
    if (TITLE_SKIP_PREFIXES.test(t)) continue;
    return t;
  }
  return null;
}

// The metadata table at the bottom of a JobServe job page is a flat sequence
// of standalone label lines (Location / Industry / Duration / …). Spec body
// emission must stop here so the metadata isn't duplicated and the footer
// chrome that follows ("Apply", "Mobile Site", country flags, etc.) is dropped.
const META_TABLE_LABELS = new Set([
  "location", "industry", "duration", "start date", "rate", "salary",
  "employment business", "employment agency", "company", "employer",
  "contact", "reference", "posted date", "permalink",
]);

function findMetadataTableStart(lines: string[]): number {
  for (let i = 0; i < lines.length; i++) {
    if (META_TABLE_LABELS.has(lines[i].trim().toLowerCase())) return i;
  }
  return lines.length;
}

export function parseSnapshotToJobRecord(
  snapshot: string,
  link: string,
): Partial<JobRecord> {
  const lines = snapshot.split("\n");
  const textLines: string[] = [];

  for (const line of lines) {
    const stripped = stripYamlSyntax(line);
    if (stripped) textLines.push(stripped);
  }

  const fullText = textLines.join("\n");
  const meta = extractMetadataPairs(textLines);

  const metaStart = findMetadataTableStart(textLines);
  const bodyLines = textLines.slice(0, metaStart);

  const title = findJobTitle(textLines) ?? extractField(fullText, ["job title", "jobtitle"]) ?? "Unknown";
  const location = meta.location ?? extractField(fullText, ["location"]) ?? "";
  const rate = meta.rate ?? extractField(fullText, ["rate", "salary", "pay rate"]) ?? "";
  const duration = meta.duration ?? extractField(fullText, ["duration", "contract length"]) ?? "";
  const employmentBusiness = meta.employmentBusiness
    ?? extractField(fullText, ["employment agency", "employment business", "employer", "company", "client"])
    ?? "";
  const contact = meta.contact ?? extractField(fullText, ["contact", "recruiter"]) ?? "";
  const posted = meta.posted ?? extractField(fullText, ["posted date", "date posted"]) ?? "";

  const specMarkdown = buildSpecMarkdown(bodyLines, title);

  return { title, location, rate, duration, employmentBusiness, contact, posted, specMarkdown };
}

// ARIA roles emitted by Playwright's accessibility-tree YAML snapshot.
const ARIA_ROLE_RE = new RegExp(
  "^(generic|paragraph|list|listitem|heading|region|navigation|main|article|" +
  "complementary|contentinfo|banner|search|form|table|cell|columnheader|" +
  "rowheader|row|separator|tab|tabpanel|tablist|menu|menuitem|menubar|toolbar|" +
  "tooltip|dialog|alert|alertdialog|status|log|marquee|timer|progressbar|" +
  "slider|spinbutton|combobox|listbox|option|textbox|checkbox|radio|" +
  "radiogroup|switch|button|link|image|img|figure|caption|code|text|note|" +
  "definition|term|insertion|deletion|strong|emphasis|blockquote|time|" +
  "document|application|group|presentation|none|toolbar)" +
  "(?:\\s+\"([^\"]+)\")?" +    // optional accessible name in double quotes
  "(?:\\s+'([^']+)')?" +        // or in single quotes
  "\\s*:\\s*(.*)$",
  "i",
);

function stripYamlSyntax(line: string): string {
  let s = line.trim();
  if (!s) return "";

  // Strip Playwright's `` ```yaml `` / `` ``` `` snapshot fence
  if (/^```/.test(s)) return "";

  if (s.startsWith("- ")) s = s.slice(2).trim();
  if (s.startsWith("#") || s.startsWith("---") || s.startsWith("...")) return "";

  // Strip ARIA-tree attribute brackets: [ref=eN], [cursor=pointer],
  // [level=N], [active], [expanded=true], [checked], [disabled], etc.
  s = s.replace(/\s*\[[^\]]+\]/g, "").trim();
  if (!s) return "";

  // Playwright accessibility-tree role lines: unwrap to the inline value, or
  // fall back to the accessible name when the role has no inline content.
  const roleMatch = s.match(ARIA_ROLE_RE);
  if (roleMatch) {
    const accName = roleMatch[2] ?? roleMatch[3] ?? "";
    const inline = (roleMatch[4] ?? "").trim();
    return inline || accName;
  }

  // Plain key:value pairs — only when the "key" is letters/spaces, so
  // timestamps like `13/05/2026 14:38:06` are passed through untouched.
  const keyValMatch = s.match(/^['"]?([^'"]+?)['"]?\s*:\s*(.*)$/);
  if (keyValMatch && /^[A-Za-z][A-Za-z\s]{0,30}$/.test(keyValMatch[1].trim())) {
    const key = keyValMatch[1].trim();
    const val = keyValMatch[2].trim();
    if (key.match(/^(ref|cursor|url|level|active)$/i)) return "";
    if (!val || val.startsWith("[") || val.startsWith("{") || /^\d+$/.test(val)) return "";
    if (key.match(/^(location|rate|salary|duration|posted|contact|title|company|employer)/i)) {
      return `${key}: ${val}`;
    }
    return val;
  }

  // Lone labels with no value
  if (/^[\w\s]+:\s*$/.test(s)) return "";

  return s;
}

function extractField(text: string, keys: string[]): string | null {
  const lower = text.toLowerCase();
  for (const key of keys) {
    const regex = new RegExp(`\\b${key}\\s*:?\\s*([^\\n]{1,300})`, 'i');
    const match = text.match(regex);
    if (match) {
      let value = match[1].trim();
      // Clean up value - remove trailing colons, quotes
      value = value.replace(/^[:"\s]+|[:"\s]+$/g, '');
      if (value && value.length > 0 && value.length < 300) {
        return value;
      }
    }
  }
  return null;
}

// Page chrome that should never appear in the spec body. Matched on prefix.
const SPEC_CHROME_RE = /^(Skip to content|JobServe(?:\s*:|\s+is)|Contact JobServe|Sign In|Register$|Home$|Job Search$|Job Seekers$|Employers$|Recruiters$|Listings$|Help$|Back to search|Apply$|Send me more jobs|Email me this job|Tell a friend|Add this to the job basket|See more jobs like this|Display Contact Details|Email$|Contact This Employment Business|Facebook$|Twitter$|LinkedIn$|img\b|Mobile Site|Contact Us|Scam Awareness|Partners$|Careers$|Terms$|Privacy$|Cookies$|United Kingdom|United States|Australia$|Canada$|More countries|Aspire Media Group|Applicants must be eligible)/i;

function buildSpecMarkdown(bodyLines: string[], jobTitle: string): string {
  const blocks: string[] = [];
  let prevBlank = true;
  let descriptionStarted = false;

  for (const raw of bodyLines) {
    const trimmed = raw.trim();
    if (!trimmed) {
      if (!prevBlank) blocks.push("");
      prevBlank = true;
      continue;
    }

    if (SPEC_CHROME_RE.test(trimmed)) continue;
    if (/^https?:\/\//.test(trimmed) || trimmed.startsWith("/url:")) continue;
    if (/^\+?\d[\d\s().\-]{6,}$/.test(trimmed)) continue;  // phone number
    if (trimmed === jobTitle) continue;                    // duplicate title line
    if (/^Posted (by|:)/i.test(trimmed)) continue;
    if (/^Contract\/Permanent|^Permanent$|^Contract$/i.test(trimmed)) continue;

    // Find first prose line: prefers a known section heading or a substantive
    // sentence (>=50 chars and contains a period).
    if (!descriptionStarted) {
      if (trimmed.match(/^(Job Description|Description|About|Role|Position|Responsibilities|Requirements|Skills|Experience|The Opportunity|What Will You Do|What We Need|Key Responsibilities|Tech stack|Must Haves|Preferred)/i) ||
          (trimmed.length > 50 && trimmed.includes("."))) {
        descriptionStarted = true;
      } else {
        continue;
      }
    }

    // Section heading (short line, capitalised, no terminal punctuation,
    // following a blank): render as inline bold.
    if (prevBlank && trimmed.length < 80 && /^[A-Z]/.test(trimmed) &&
        !trimmed.endsWith(".") &&
        !/^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)/.test(trimmed)) {
      blocks.push(`**${trimmed}**`);
      prevBlank = false;
      continue;
    }

    if (trimmed.startsWith("•") || trimmed.startsWith("·") ||
        (trimmed.startsWith("-") && trimmed.length > 2)) {
      blocks.push(`- ${trimmed.replace(/^[•·\-]\s*/, "")}`);
    } else {
      blocks.push(trimmed);
    }
    prevBlank = false;
  }

  // Collapse runs of blank lines
  const collapsed: string[] = [];
  for (const b of blocks) {
    if (b === "" && collapsed[collapsed.length - 1] === "") continue;
    collapsed.push(b);
  }
  return collapsed.join("\n").trim();
}

async function scoreJob(
  job: JobRecord,
  cvContent: string,
): Promise<{ score: number; reason: string }> {
  if (!job.retrieved) {
    return { score: 0, reason: "Job specification could not be retrieved." };
  }

  const prompt = `You are evaluating a candidate's suitability for a job based strictly on their CV.

CV:
${cvContent.slice(0, 6000)}

Job Title: ${job.title}
Job Location: ${job.location}
Job Rate: ${job.rate}
Job Duration: ${job.duration}

Job Specification:
${job.specMarkdown.slice(0, 4000)}

Score the candidate's suitability from 0 to 100 based only on the CV content above.
Respond with a JSON object: {"score": <number>, "reason": "<one paragraph explanation>"}
Do not use external knowledge. Base your assessment solely on what is in the CV.`;

  try {
    const [text] = await createMessage(
      "claude-haiku-4-5-20251001",
      512,
      [{ role: "user", content: prompt }],
    );

    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return { score: 0, reason: "Could not parse scoring response." };

    const parsed = JSON.parse(jsonMatch[0]) as { score?: number; reason?: string };
    return {
      score: typeof parsed.score === "number" ? Math.min(100, Math.max(0, parsed.score)) : 0,
      reason: parsed.reason ?? "No reason provided.",
    };
  } catch (err) {
    console.error(`[jobserve-processor] Scoring failed for ${job.title}: ${err}`);
    return { score: 0, reason: `Scoring error: ${String(err)}` };
  }
}

function humanDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

function blockquote(text: string): string[] {
  if (!text) return [];
  return text.split("\n").map((l) => (l === "" ? ">" : `> ${l}`));
}

function buildReport(jobs: JobRecord[], reportDate: string): string {
  // Group jobs by source email in first-seen order, preserving email order
  // within each group (cowork-style — no global score sort).
  const groups = new Map<string, JobRecord[]>();
  for (const job of jobs) {
    const key = job.emailSubject || "Unknown source";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(job);
  }

  const lines: string[] = [];
  lines.push(`# JobServe Jobs — ${humanDate(reportDate)}`);
  lines.push("");
  lines.push(`Source: emails from JobServe ("Daily Jobs By Email"), received ${humanDate(reportDate)}.`);
  if (groups.size >= 1) {
    lines.push(`${groups.size} email${groups.size === 1 ? "" : "s"} processed:`);
    for (const [subj, js] of groups) {
      lines.push(`- **${js.length} job${js.length === 1 ? "" : "s"}** — ${subj}`);
    }
  }
  lines.push("");
  lines.push("Each entry below contains the job specification as retrieved from the JobServe listing page, followed by a suitability ranking (0–100) and rank reason based on the candidate's CV.");
  lines.push("");

  let emailIdx = 0;
  for (const [subj, groupJobs] of groups) {
    emailIdx++;
    lines.push("---");
    lines.push("");
    lines.push(`## Email ${emailIdx} — ${subj} (${groupJobs.length} job${groupJobs.length === 1 ? "" : "s"})`);
    lines.push("");

    let entryIdx = 0;
    for (const job of groupJobs) {
      entryIdx++;
      lines.push("---");
      lines.push("");
      lines.push(`### ${entryIdx}. ${job.title}`);
      lines.push("");
      lines.push(`- **Location:** ${job.location || "N/A"}`);
      lines.push(`- **Rate:** ${job.rate || "N/A"}`);
      lines.push(`- **Duration:** ${job.duration || "N/A"}`);
      const eb = job.employmentBusiness || "N/A";
      const contactPart = job.contact ? ` (Contact: ${job.contact})` : "";
      lines.push(`- **Employment Business:** ${eb}${contactPart}`);
      lines.push(`- **Posted:** ${job.posted || "N/A"}`);
      lines.push(`- **Link:** ${job.link}`);
      lines.push("");
      lines.push("**Full job specification (from JobServe page):**");
      lines.push("");

      if (!job.retrieved) {
        lines.push("> _Full JobServe specification not retrieved._");
        if (job.errorReason) lines.push(`> _Reason: ${job.errorReason}_`);
      } else if (job.specMarkdown) {
        lines.push(...blockquote(job.specMarkdown));
      } else {
        lines.push("> _No specification content extracted._");
      }

      lines.push("");
      lines.push(`- **Suitability ranking: ${job.score}/100**`);
      lines.push(`- **Rank reason:** ${job.scoreReason}`);
      lines.push("");
    }
  }

  return lines.join("\n");
}