/**
 * jobserve_email_processor — generated codegen task.
 *
 * Reads recent JobServe "Daily Jobs By Email" alerts, parses each email into
 * job blocks (title + blurb + link), fetches the full specification from each
 * linked JobServe page, scores every job against the candidate CV with an LLM,
 * drafts a short cover letter per job, and writes one markdown report per
 * email date.
 *
 * Design note: the email body is the PRIMARY source. Every job keeps its
 * verbatim email blurb, which is used as the specification fallback when the
 * JobServe listing has expired or cannot be fetched — so a dead link never
 * loses a job.
 */

import { readFileSync } from "node:fs";

import type { Clients } from "./tools.js";
import { gmailSearch, gmailRead, webFetch } from "./tools.js";
import { writeFile } from "../../_runtime/src/utils.js";
import { createMessage } from "../../_runtime/src/llm.js";

export const SERVERS: string[] = ["google", "web"];
export const TOOL_NAME = "jobserve_email_processor";
export const TOOL_DESCRIPTION =
  "Parses JobServe job-alert emails into individual jobs, fetches each full specification, " +
  "scores them against a CV with rank reasons, drafts a brief cover letter per job, and " +
  "writes a dated markdown report per email date.";
export const TOOL_INPUT_SCHEMA = {};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Profile {
  sender?: string;
  days_back?: number;
  max_jobs?: number;
  cv_path?: string;
  output_dir?: string;
  rank_model?: string;
}

export interface Job {
  title: string;
  url: string;
  blurb: string; // verbatim text of the email block — the expiry fallback
  spec: string; // full spec from the JobServe page ("" if not retrieved)
  retrieved: boolean;
  expired: boolean;
  errorReason: string;
  location: string;
  rate: string;
  duration: string;
  posted: string;
  score: number;
  reason: string;
  coverLetter: string;
  emailDate: string; // YYYY-MM-DD
  emailSubject: string;
}

export interface EmailRecord {
  date: string;
  subject: string;
  jobs: Job[];
}

interface ParsedBlock {
  title: string;
  url: string;
  blurb: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SENDER = "jobsbyemail@apps.jobserve.com";
const DEFAULT_DAYS_BACK = 2;
const DEFAULT_MAX_JOBS = 60;
const DEFAULT_RANK_MODEL = "claude-sonnet-4-6";

// JobServe per-job listing links inside the alert email. The W<hash>.jsjob form
// is the listing page; the query string carries the alert tracking token.
const JOBSERVE_LINK_RE =
  /https?:\/\/(?:www\.)?jobserve\.com\/[A-Za-z0-9]+\.jsjob\?[^\s)\]'"<>]+/i;
const JOBSERVE_LINK_RE_G =
  /https?:\/\/(?:www\.)?jobserve\.com\/[A-Za-z0-9]+\.jsjob\?[^\s)\]'"<>]+/gi;

// Jobs in the plain-text email are separated by long dashed rules.
const SEPARATOR_RE = /-{15,}/;

interface Band {
  name: string;
  min: number;
}

const BANDS: Band[] = [
  { name: "Top Matches (75–100)", min: 75 },
  { name: "Strong Prospects (50–74)", min: 50 },
  { name: "Possible (25–49)", min: 25 },
  { name: "Weak Matches (0–24)", min: 0 },
];

// ---------------------------------------------------------------------------
// Email parsing
// ---------------------------------------------------------------------------

/** Strip HTML to plain text when the email body is an HTML part. */
function normalizeBody(body: string): string {
  if (!/<\w+[\s>]/.test(body)) return body; // already plain text
  return body
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/\s*(?:p|div|tr|li|h[1-6])\s*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&quot;/gi, '"')
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n");
}

function isUrlLine(line: string): boolean {
  return /^https?:\/\//i.test(line);
}

function cleanTitle(line: string): string {
  return (
    line
      .replace(/\s+/g, " ")
      .replace(/[*_`]+/g, "")
      .trim()
      .slice(0, 200) || "Untitled role"
  );
}

/**
 * Parse an email body into one job per dashed block that contains a JobServe
 * link. The first non-URL line of the block is the title; the whole block is
 * kept as the blurb. Falls back to bare links if the body has no dashed blocks
 * (e.g. an HTML-only email) so a run still produces something.
 */
export function extractJobs(rawBody: string): ParsedBlock[] {
  const body = normalizeBody(rawBody);
  const out: ParsedBlock[] = [];
  const seen = new Set<string>();

  for (const block of body.split(SEPARATOR_RE)) {
    const m = block.match(JOBSERVE_LINK_RE);
    if (!m || seen.has(m[0])) continue;
    const lines = block
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) continue;
    seen.add(m[0]);
    out.push({
      title: cleanTitle(lines.find((l) => !isUrlLine(l)) ?? lines[0]),
      url: m[0],
      blurb: lines.join("\n"),
    });
  }
  if (out.length > 0) return out;

  // Fallback: scan the raw body so links inside href="..." attributes survive.
  for (const url of rawBody.match(JOBSERVE_LINK_RE_G) ?? []) {
    if (seen.has(url)) continue;
    seen.add(url);
    out.push({ title: "JobServe listing", url, blurb: "" });
  }
  return out;
}

function parseEmailDate(dateStr: string): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return new Date().toISOString().slice(0, 10);
  return d.toISOString().slice(0, 10);
}

function newJob(src: ParsedBlock, emailDate: string, emailSubject: string): Job {
  return {
    title: src.title,
    url: src.url,
    blurb: src.blurb,
    spec: "",
    retrieved: false,
    expired: false,
    errorReason: "",
    location: "",
    rate: "",
    duration: "",
    posted: "",
    score: 0,
    reason: "",
    coverLetter: "",
    emailDate,
    emailSubject,
  };
}

// ---------------------------------------------------------------------------
// Job page retrieval
// ---------------------------------------------------------------------------

function cleanSpec(text: string): string {
  return text
    .split("\n")
    .map((l) => l.replace(/[ \t]+/g, " ").trimEnd())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, 8000);
}

interface SpecResult {
  spec: string;
  retrieved: boolean;
  expired: boolean;
  errorReason: string;
}

async function retrieveSpec(clients: Clients, url: string): Promise<SpecResult> {
  try {
    const res = await webFetch(clients, url);
    if (!res) {
      return { spec: "", retrieved: false, expired: false, errorReason: "Fetch returned no result." };
    }
    if (res.status_code >= 400) {
      const expired = res.status_code === 404 || res.status_code === 410;
      return { spec: "", retrieved: false, expired, errorReason: `HTTP ${res.status_code}` };
    }
    const content = (res.content ?? "").trim();
    if (/no longer available|has expired|job has been filled|vacancy is closed/i.test(content)) {
      return {
        spec: "",
        retrieved: false,
        expired: true,
        errorReason: "Listing no longer available on JobServe.",
      };
    }
    if (content.length < 120) {
      return { spec: "", retrieved: false, expired: false, errorReason: "Page returned little or no content." };
    }
    return { spec: cleanSpec(content), retrieved: true, expired: false, errorReason: "" };
  } catch (err) {
    return { spec: "", retrieved: false, expired: false, errorReason: String(err) };
  }
}

/** Best-effort metadata extraction from label/value lines in blurb + spec. */
function extractField(text: string, labels: string[]): string {
  for (const label of labels) {
    const re = new RegExp(`(?:^|\\n)\\s*${label}\\s*[:\\-]\\s*([^\\n]{1,160})`, "i");
    const m = text.match(re);
    if (m) {
      const v = m[1].trim().replace(/[*_`]+/g, "");
      if (v) return v;
    }
  }
  return "";
}

// ---------------------------------------------------------------------------
// Scoring + cover letter (one LLM call per job)
// ---------------------------------------------------------------------------

export interface Assessment {
  score: number;
  reason: string;
  coverLetter: string;
}

/** Parse the assessment JSON, tolerating code fences and surrounding prose. */
export function parseAssessment(text: string): Assessment {
  let t = text
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
  const m = t.match(/\{[\s\S]*\}/);
  if (m) t = m[0];
  try {
    const obj = JSON.parse(t) as {
      ranking?: unknown;
      score?: unknown;
      reason?: unknown;
      coverLetter?: unknown;
    };
    const raw =
      typeof obj.ranking === "number"
        ? obj.ranking
        : typeof obj.score === "number"
          ? obj.score
          : 0;
    return {
      score: Math.max(0, Math.min(100, Math.round(raw))),
      reason: typeof obj.reason === "string" ? obj.reason.trim() : "No reason provided.",
      coverLetter: typeof obj.coverLetter === "string" ? obj.coverLetter.trim() : "",
    };
  } catch {
    return { score: 0, reason: "Could not parse the assessment response.", coverLetter: "" };
  }
}

async function assessJob(model: string, cv: string, job: Job): Promise<Assessment> {
  const jobText = job.spec || job.blurb;
  if (!jobText.trim()) {
    return { score: 0, reason: "No job specification or email text was available to assess.", coverLetter: "" };
  }

  const prompt = `You assess how well a contract or permanent role suits a specific candidate, using ONLY their CV.

<cv>
${cv.slice(0, 12000)}
</cv>

<job>
Title: ${job.title}
${job.location ? `Location: ${job.location}\n` : ""}${job.rate ? `Rate: ${job.rate}\n` : ""}Specification:
${jobText.slice(0, 6000)}
</job>

Do three things:
1. Score suitability 0-100 (0 = no fit, 50 = partial fit, 100 = excellent fit on technology, seniority, domain, location and rate). Judge strictly against the CV.
2. Give a concrete one-paragraph reason naming specific CV strengths and gaps against this job.
3. Write a very brief cover letter (3-5 sentences, under 120 words) the candidate could adapt when applying — first person, specific to this role, no placeholders other than [Name].

Respond with ONLY a JSON object, no prose, no code fences:
{"ranking": <integer 0-100>, "reason": "<one paragraph>", "coverLetter": "<the letter>"}`;

  try {
    const [text] = await createMessage(model, 1200, [{ role: "user", content: prompt }], {
      temperature: 0.3,
    });
    return parseAssessment(text);
  } catch (err) {
    return { score: 0, reason: `Assessment failed: ${String(err)}`, coverLetter: "" };
  }
}

// ---------------------------------------------------------------------------
// Report rendering
// ---------------------------------------------------------------------------

export function bandFor(score: number): string {
  for (const b of BANDS) {
    if (score >= b.min) return b.name;
  }
  return "Weak Matches (0–24)";
}

function humanDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function blockquote(text: string): string {
  if (!text.trim()) return "> _(none)_";
  return text
    .split("\n")
    .map((l) => (l.trim() ? `> ${l}` : ">"))
    .join("\n");
}

function renderJob(n: number, job: Job): string[] {
  const out: string[] = [];
  out.push(`### ${n}. ${job.title} — ${job.score}/100`);
  out.push("");
  out.push(`- **Location:** ${job.location || "N/A"}`);
  out.push(`- **Rate:** ${job.rate || "N/A"}`);
  out.push(`- **Duration:** ${job.duration || "N/A"}`);
  out.push(`- **Posted:** ${job.posted || "N/A"}`);
  out.push(`- **Source email:** ${job.emailSubject || "N/A"} (${job.emailDate})`);
  out.push(`- **Link:** ${job.url}`);
  out.push("");
  out.push("**Job specification:**");
  out.push("");
  if (job.retrieved) {
    out.push(blockquote(job.spec));
  } else {
    out.push(`> _Full JobServe listing not retrieved — ${job.errorReason || "unknown reason"}._`);
    out.push(">");
    out.push("> _Specification below is the job summary from the alert email:_");
    out.push(">");
    out.push(blockquote(job.blurb));
  }
  out.push("");
  out.push(`**Suitability: ${job.score}/100**`);
  out.push("");
  out.push(job.reason || "_No reason provided._");
  out.push("");
  out.push("**Cover letter:**");
  out.push("");
  out.push(job.coverLetter ? blockquote(job.coverLetter) : "> _Not generated._");
  out.push("");
  return out;
}

export function buildReport(reportDate: string, emails: EmailRecord[], jobs: Job[]): string {
  const lines: string[] = [];
  lines.push(`# JobServe Jobs — ${humanDate(reportDate)}`);
  lines.push("");
  lines.push(`**Source:** JobServe "Daily Jobs By Email" alerts received ${humanDate(reportDate)}.`);
  lines.push(`**Emails processed:** ${emails.length} · **Jobs:** ${jobs.length}`);
  for (const e of emails) {
    lines.push(`- ${e.jobs.length} job${e.jobs.length === 1 ? "" : "s"} — ${e.subject}`);
  }
  lines.push("");
  lines.push(
    "Each entry has the full job specification (from the JobServe listing, or the email " +
      "text when the listing has expired), a CV-based suitability score (0–100) with " +
      "reasoning, and a short cover letter to adapt when applying.",
  );
  lines.push("");

  const scores = jobs.map((j) => j.score);
  const avg = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0;
  const top = scores.length ? Math.max(...scores) : 0;
  const notRetrieved = jobs.filter((j) => !j.retrieved).length;

  lines.push("## Summary");
  lines.push("");
  lines.push(`- **Jobs ranked:** ${jobs.length}`);
  lines.push(`- **Average score:** ${avg}/100`);
  lines.push(`- **Highest score:** ${top}/100`);
  if (notRetrieved > 0) {
    lines.push(`- **Listings not retrievable (ranked from email text):** ${notRetrieved}`);
  }
  lines.push("");

  const sorted = [...jobs].sort((a, b) => b.score - a.score);
  let entryNo = 0;
  for (const band of BANDS) {
    const inBand = sorted.filter((j) => bandFor(j.score) === band.name);
    if (inBand.length === 0) continue;
    lines.push("---");
    lines.push("");
    lines.push(`## ${band.name}`);
    lines.push(`*${inBand.length} role${inBand.length === 1 ? "" : "s"}*`);
    lines.push("");
    for (const job of inBand) {
      entryNo++;
      lines.push(...renderJob(entryNo, job));
    }
  }

  return lines.join("\n").trim() + "\n";
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export async function handleTool(
  _input: Record<string, never>,
  clients: Clients,
  profile: Record<string, unknown>,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const p = profile as Profile;
  const sender = p.sender ?? DEFAULT_SENDER;
  const daysBack = p.days_back ?? DEFAULT_DAYS_BACK;
  const maxJobs = p.max_jobs ?? DEFAULT_MAX_JOBS;
  const cvPath = p.cv_path ?? "";
  const outputDir = p.output_dir ?? ".";
  const rankModel = p.rank_model ?? DEFAULT_RANK_MODEL;

  // --- CV -------------------------------------------------------------------
  if (!cvPath) return { error: "profile.cv_path is not set." };
  let cv: string;
  try {
    cv = readFileSync(cvPath, "utf-8");
  } catch (err) {
    return { error: `Cannot read CV at ${cvPath}: ${String(err)}` };
  }
  if (!cv.trim()) return { error: `CV file at ${cvPath} is empty.` };

  // --- Emails ---------------------------------------------------------------
  const query = `from:${sender} newer_than:${daysBack}d`;
  console.error(`[jobserve_email_processor] Gmail search: ${query}`);
  let metas: Array<Record<string, string>>;
  try {
    metas = await gmailSearch(clients, query, 50);
  } catch (err) {
    return { error: `Gmail search failed: ${String(err)}` };
  }
  if (metas.length === 0) {
    return { message: `No emails from ${sender} in the last ${daysBack} day(s).`, jobs_processed: 0 };
  }

  const emails: EmailRecord[] = [];
  const seenUrls = new Set<string>();
  let total = 0;
  for (const meta of metas) {
    if (total >= maxJobs) break;
    const id = meta["id"] ?? meta["messageId"];
    if (!id) continue;
    let data: Record<string, string> | null;
    try {
      data = await gmailRead(clients, id);
    } catch (err) {
      console.error(`[jobserve_email_processor] gmailRead ${id} failed: ${err}`);
      continue;
    }
    if (!data) continue;
    const emailDate = parseEmailDate(data["date"] ?? "");
    const emailSubject = (data["subject"] ?? "JobServe alert").trim();
    const jobs: Job[] = [];
    for (const block of extractJobs(data["body"] ?? "")) {
      if (total >= maxJobs) break;
      if (seenUrls.has(block.url)) continue;
      seenUrls.add(block.url);
      total++;
      jobs.push(newJob(block, emailDate, emailSubject));
    }
    emails.push({ date: emailDate, subject: emailSubject, jobs });
  }

  const allJobs = emails.flatMap((e) => e.jobs);
  if (allJobs.length === 0) {
    return { message: "Emails found, but no JobServe job links could be parsed.", jobs_processed: 0 };
  }

  // --- Retrieve specifications ---------------------------------------------
  console.error(`[jobserve_email_processor] Retrieving ${allJobs.length} job spec(s)`);
  for (const job of allJobs) {
    const r = await retrieveSpec(clients, job.url);
    job.spec = r.spec;
    job.retrieved = r.retrieved;
    job.expired = r.expired;
    job.errorReason = r.errorReason;
    const meta = `${job.blurb}\n${job.spec}`;
    job.location = extractField(meta, ["location"]);
    job.rate = extractField(meta, ["rate", "salary", "pay rate", "day rate"]);
    job.duration = extractField(meta, ["duration", "contract length", "term"]);
    job.posted = extractField(meta, ["posted", "posted date", "date posted"]);
  }

  // --- Score + cover letter ------------------------------------------------
  console.error(`[jobserve_email_processor] Scoring ${allJobs.length} job(s) against CV`);
  for (const job of allJobs) {
    const a = await assessJob(rankModel, cv, job);
    job.score = a.score;
    job.reason = a.reason;
    job.coverLetter = a.coverLetter;
  }

  // --- Report per email date ----------------------------------------------
  const byDate = new Map<string, EmailRecord[]>();
  for (const e of emails) {
    const list = byDate.get(e.date);
    if (list) list.push(e);
    else byDate.set(e.date, [e]);
  }

  const written: string[] = [];
  const cleanOutputDir = outputDir.replace(/[\\/]+$/, "");
  for (const [date, recs] of byDate) {
    const dateJobs = recs.flatMap((r) => r.jobs);
    const report = buildReport(date, recs, dateJobs);
    const resolved = await writeFile(`${cleanOutputDir}/${date}-js-content.md`, report, config);
    written.push(resolved);
    console.error(`[jobserve_email_processor] Wrote ${resolved}`);
  }

  const allScores = allJobs.map((j) => j.score);
  return {
    jobs_processed: allJobs.length,
    emails_processed: emails.length,
    files_written: written,
    top_score: allScores.length ? Math.max(...allScores) : 0,
    average_score: allScores.length
      ? Math.round(allScores.reduce((a, b) => a + b, 0) / allScores.length)
      : 0,
  };
}
