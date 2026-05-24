/**
 * jobserve_rss_processor — generated codegen task.
 *
 * Reads job items from a JobServe RSS feed (currently the saved sample file,
 * later a live feed URL). For each date it maintains two paired files in the
 * output directory:
 *
 *   YYYY-MM-DD-js-rss-data.json  — the sidecar: exact job records (source of truth)
 *   YYYY-MM-DD-js-rss-data.md    — the rendered, score-banded report for humans
 *
 * Each run loads the sidecar, scores only feed items not already in it, merges,
 * and rewrites both files. Jobs already recorded are never re-scored. Because
 * the data lives in the JSON, the .md is pure presentation — its layout can be
 * changed freely without affecting incremental runs.
 */

import { existsSync, readFileSync } from "node:fs";

import TurndownService from "turndown";
import { z } from "zod";

import type { Clients } from "./tools.js";
import { webFetch } from "./tools.js";
import { writeFile, resolveOutputPath } from "../../_runtime/src/utils.js";
import { createMessage } from "../../_runtime/src/llm.js";
import { defineTools } from "../../_runtime/src/tool-def.js";

// `web` is declared so a live feed URL works with no code change — the current
// sample-file path needs no server, but connecting an unused one is harmless.
export const SERVERS: string[] = ["web"];
export const SERVER_NAME = "jobserve_rss_processor";

// The exposed MCP tools are declared at the bottom of this file as `TOOLS`.
// Per-tool name / description / inputSchema live there alongside their handler.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Profile {
  rss_source?: string; // local file path, or an http(s) URL for a live feed
  cv_path?: string;
  output_dir?: string;
  rank_model?: string;
  max_jobs?: number; // 0 = no limit
}

export interface RssItem {
  title: string;
  link: string;
  guid: string;
  pubDate: string;
  description: string; // raw — still entity-encoded
}

interface RssJob {
  title: string;
  link: string;
  guid: string;
  pubDate: string;
  description: string; // cleaned plain text
  location: string;
  rate: string;
}

/** A fully scored job — the unit stored in the .json sidecar. */
export interface StoredJob {
  guid: string;
  title: string;
  link: string;
  location: string;
  rate: string;
  pubDate: string;
  score: number; // 0-10, one decimal
  reason: string;
  coverLetter: string;
  description: string; // full cleaned job text from the RSS feed
}

export interface Assessment {
  score: number;
  reason: string;
  coverLetter: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_RANK_MODEL = "claude-sonnet-4-6";
const UNKNOWN_DATE = "unknown-date";

interface Band {
  key: string;
  heading: string;
  min: number;
}

// Bands mirror jobsearch/example-job-report.md (0-10 scale).
const BANDS: Band[] = [
  { key: "Top Match", heading: "Top Matches (7–10)", min: 7 },
  { key: "Solid Prospect", heading: "Solid Prospects (4.5–6.9)", min: 4.5 },
  { key: "Unlikely Match", heading: "Unlikely Matches (2–4.4)", min: 2 },
  { key: "Poor Match", heading: "Poor Matches (0–1.9)", min: 0 },
];

// ---------------------------------------------------------------------------
// RSS parsing
// ---------------------------------------------------------------------------

function tag(block: string, name: string): string {
  const m = block.match(new RegExp(`<${name}\\b[^>]*>([\\s\\S]*?)<\\/${name}>`, "i"));
  return m?.[1]?.trim() ?? "";
}

function safeCodePoint(n: number): string {
  if (!Number.isFinite(n) || n <= 0 || n > 0x10ffff) return "";
  try {
    return String.fromCodePoint(n);
  } catch {
    return "";
  }
}

/** Decode XML / HTML entities (one pass). `&amp;` is decoded last on purpose. */
function decodeEntities(s: string): string {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&apos;/gi, "'")
    .replace(/&nbsp;/gi, " ")
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h: string) => safeCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d: string) => safeCodePoint(parseInt(d, 10)))
    .replace(/&amp;/gi, "&");
}

const turndown = new TurndownService({
  headingStyle: "atx",
  bulletListMarker: "-",
  emDelimiter: "*",
  strongDelimiter: "**",
});

/**
 * Make the JobServe description HTML turndown-friendly:
 *   - drop decorative bullet images
 *   - flatten the footer table: each <tr> becomes one line (image · label · spacer · value
 *     cells collapse into "**Label:** Value" inline), so trimAdminFooter can read it
 *   - rewrite inline `font-weight: bold` spans as <strong> so they render as **bold**
 */
function preprocessHtml(html: string): string {
  return html
    .replace(/<img\b[^>]*\/?>/gi, "")
    .replace(/<\/?(?:table|tbody|thead)\b[^>]*>/gi, "")
    .replace(/<\/tr>/gi, "<br/>")
    .replace(/<tr\b[^>]*>/gi, "")
    .replace(/<\/?(?:td|th)\b[^>]*>/gi, " ")
    .replace(
      /<span\b[^>]*style\s*=\s*["'][^"']*font-weight\s*:\s*(?:bold|[6-9]\d{2})[^"']*["'][^>]*>([\s\S]*?)<\/span>/gi,
      "<strong>$1</strong>",
    );
}

/** Drop a leading "Rate: X Location: Y" header that just repeats the metadata
 *  line shown above the description. */
function stripLeadingRateLocation(md: string): string {
  const lines = md.split("\n");
  let i = 0;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (t === "") { i++; continue; }
    if (/^(?:\*\*)?(?:Rate|Location)\b/i.test(t)) { i++; continue; }
    break;
  }
  return lines.slice(i).join("\n").replace(/^\s+/, "");
}

const ADMIN_DROP_RE =
  /^(?:\*\*)?(?:Reference|Email|Advertiser|Country|Rate|Location)\s*:(?:\*\*)?.*$/i;
const ADMIN_KEEP_RE =
  /^(?:\*\*)?(Contact|Type|Start\s*Date)\s*:(?:\*\*)?\s*(.+)$/i;

/** Trim the JobServe admin block at the bottom of a description: drop pure
 *  noise (Reference / Email / Advertiser / Country / duplicate Rate / Location)
 *  and collapse kept fields (Contact / Type / Start Date) onto one line. */
function trimAdminFooter(md: string): string {
  const lines = md.split("\n");
  let i = lines.length - 1;
  while (i >= 0 && lines[i].trim() === "") i--;
  const kept: string[] = [];
  let touched = false;
  while (i >= 0) {
    const line = lines[i].trim();
    if (!line) break;
    if (ADMIN_DROP_RE.test(line)) {
      touched = true;
      i--;
      continue;
    }
    const m = ADMIN_KEEP_RE.exec(line);
    if (m) {
      touched = true;
      kept.unshift(`${m[1]}: ${m[2].replace(/\*+/g, "").trim()}`);
      i--;
      continue;
    }
    break;
  }
  if (!touched) return md;
  const body = lines.slice(0, i + 1).join("\n").trimEnd();
  if (kept.length === 0) return body;
  return `${body}\n\n${kept.join(" · ")}`;
}

// Known section headings found inside the body of JobServe descriptions.
// Recruiters write the body as one inline string with these phrases buried
// mid-paragraph; injecting a bold heading + paragraph break around them
// turns a wall of text into readable sections.
//
// IMPORTANT: only multi-word distinctive phrases — single common words like
// "Experience", "Requirements", "Skills" would match mid-sentence prose
// (e.g. "Hands-on experience with Azure") and break the body.
const SECTION_HEADINGS = [
  // "Hays-style" — sentence-case, often followed by " :"
  "What you'll need to succeed",
  "What you'll get in return",
  "What you need to do now",
  // Title-case from various agencies
  "Key Responsibilities",
  "What You Will Ideally Bring",
  "What You Will Bring",
  "What You'll Bring",
  "Required Skills",
  "Required Experience",
  "Contract Details",
  "Role Overview",
  "Day-to-Day",
  "Day to Day",
  "About You",
  "About Us",
  "About The Role",
  "About The Company",
  "Nice to Have",
  "What We Offer",
];

/** Inject `\n\n**heading**\n\n` around any known section heading found inline.
 *  Conservative — only known headings from the list above, longest first so
 *  "What You'll Need to Succeed" wins over a shorter "What You'll Need". */
function injectSectionBreaks(md: string): string {
  const alt = [...SECTION_HEADINGS]
    .sort((a, b) => b.length - a.length)
    .map((h) => h.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  const re = new RegExp(`(?<=\\s|^)(${alt})\\s*:?\\s+`, "gi");
  return md.replace(re, (_, h: string) => `\n\n**${h.trim()}**\n\n`);
}

/**
 * Convert the RSS <description> HTML to clean markdown body text.
 *
 * The <description> is doubly encoded — XML entities wrap an HTML fragment.
 * We decode the outer layer, hand the inner HTML to turndown (after promoting
 * inline-styled bold spans to <strong> and flattening the footer table),
 * then trim the redundant leading Rate/Location header, JobServe's boilerplate
 * admin footer, and inject section breaks where known headings appear inline.
 */
export function cleanDescription(raw: string): string {
  const html = decodeEntities(raw);
  let md = turndown.turndown(preprocessHtml(html));
  md = md.replace(/\xa0/g, " "); // non-breaking spaces -> regular spaces
  md = stripLeadingRateLocation(md);
  md = trimAdminFooter(md);
  md = injectSectionBreaks(md);
  return md
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, 6000);
}

/** Parse <item> elements out of an RSS document. */
export function parseRssItems(xml: string): RssItem[] {
  const items: RssItem[] = [];
  const itemRe = /<item\b[^>]*>([\s\S]*?)<\/item>/gi;
  let m: RegExpExecArray | null;
  while ((m = itemRe.exec(xml)) !== null) {
    const block = m[1] ?? "";
    if (!block) continue;
    const title = decodeEntities(tag(block, "title"));
    const link = decodeEntities(tag(block, "link"));
    const guid = decodeEntities(tag(block, "guid")) || link;
    const pubDate = decodeEntities(tag(block, "pubDate"));
    if (!title && !link) continue;
    items.push({ title, link, guid, pubDate, description: tag(block, "description") });
  }
  return items;
}

export function pubDateToISO(pubDate: string): string {
  const d = new Date(pubDate);
  if (isNaN(d.getTime())) return UNKNOWN_DATE;
  return d.toISOString().slice(0, 10);
}

/** Pull an inline "Label: value" field out of the cleaned description. */
function fieldFrom(text: string, label: string): string {
  const m = text.match(new RegExp(`${label}\\s*:\\s*([^\\n]+)`, "i"));
  if (!m?.[1]) return "";
  let v = m[1];
  const cut = v.search(/\b(?:Rate|Location|Type|Duration|Start\s*Date|Reference)\s*:/i);
  if (cut > 0) v = v.slice(0, cut);
  return v.replace(/\s+/g, " ").trim().slice(0, 160);
}

function enrich(item: RssItem): RssJob {
  const description = cleanDescription(item.description);
  return {
    title: item.title || "Untitled role",
    link: item.link,
    guid: item.guid || item.link,
    pubDate: item.pubDate,
    description,
    location: fieldFrom(description, "Location"),
    rate: fieldFrom(description, "Rate"),
  };
}

// ---------------------------------------------------------------------------
// Scoring + cover letter (one LLM call per new job)
// ---------------------------------------------------------------------------

/** Parse the assessment JSON (0-10 scale), tolerating fences and stray prose. */
export function parseAssessment(text: string): Assessment {
  let t = text
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
  const m = t.match(/\{[\s\S]*\}/);
  if (m?.[0]) t = m[0];
  try {
    const o = JSON.parse(t) as {
      ranking?: unknown;
      score?: unknown;
      reason?: unknown;
      coverLetter?: unknown;
    };
    const raw =
      typeof o.ranking === "number" ? o.ranking : typeof o.score === "number" ? o.score : 0;
    return {
      score: Math.max(0, Math.min(10, Math.round(raw * 10) / 10)),
      reason: typeof o.reason === "string" ? o.reason.trim() : "No reason provided.",
      coverLetter: typeof o.coverLetter === "string" ? o.coverLetter.trim() : "",
    };
  } catch {
    return { score: 0, reason: "Could not parse the assessment response.", coverLetter: "" };
  }
}

// Returns null on transient LLM failure (network, rate limit, etc.) so the
// caller can skip storing the job and let the next run retry. A permanent
// "no description" case still returns a real score=0 record.
async function assessJob(model: string, cv: string, job: RssJob): Promise<Assessment | null> {
  if (!job.description.trim()) {
    return { score: 0, reason: "No job description was available to assess.", coverLetter: "" };
  }
  const prompt = `You assess how well a job suits a specific candidate, using ONLY their CV.

<cv>
${cv.slice(0, 12000)}
</cv>

<job>
Title: ${job.title}
${job.location ? `Location: ${job.location}\n` : ""}${job.rate ? `Rate: ${job.rate}\n` : ""}Description:
${job.description.slice(0, 5000)}
</job>

Do three things:
1. Score suitability 0-10 (one decimal allowed; 0 = no fit, 5 = partial fit, 10 = excellent fit on technology, seniority, domain, location and rate). Judge strictly against the CV.
2. Give a concrete one-paragraph reason naming specific CV strengths and gaps against this job.
3. Write a very brief cover letter (3-5 sentences, under 120 words) the candidate could adapt when applying — first person, specific to this role, no placeholders other than [Name].

Respond with ONLY a JSON object, no prose, no code fences:
{"ranking": <number 0-10>, "reason": "<one paragraph>", "coverLetter": "<the letter>"}`;
  try {
    const [text] = await createMessage(model, 1200, [{ role: "user", content: prompt }], {
      temperature: 0.3,
    });
    return parseAssessment(text);
  } catch (err) {
    console.error(`[jobserve_rss_processor] Assessment failed for ${job.title}: ${String(err)}`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sidecar — the .json file is the source of truth for incremental runs.
// ---------------------------------------------------------------------------

function coerceStored(o: Record<string, unknown>): StoredJob {
  const str = (v: unknown): string => (typeof v === "string" ? v : "");
  const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
  return {
    guid: str(o.guid) || str(o.link),
    title: str(o.title) || "Untitled role",
    link: str(o.link),
    location: str(o.location),
    rate: str(o.rate),
    pubDate: str(o.pubDate),
    score: Math.max(0, Math.min(10, num(o.score))),
    reason: str(o.reason),
    coverLetter: str(o.coverLetter),
    description: str(o.description),
  };
}

/** Deserialize a sidecar's JSON text into job records. Lenient — bad input yields []. */
export function parseSidecar(raw: string): StoredJob[] {
  try {
    const data = JSON.parse(raw) as unknown;
    if (!Array.isArray(data)) return [];
    return data
      .filter((o): o is Record<string, unknown> => !!o && typeof o === "object")
      .map(coerceStored)
      .filter((j) => j.guid.length > 0);
  } catch {
    return [];
  }
}

/** Serialize job records to sidecar JSON text. */
export function serializeSidecar(jobs: StoredJob[]): string {
  return JSON.stringify(jobs, null, 2) + "\n";
}

/** Read a file's text, or "" if it does not exist / cannot be read. */
function readIfExists(path: string): string {
  try {
    return existsSync(path) ? readFileSync(path, "utf-8") : "";
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------
// Rendering (the .md report — pure presentation, never read back)
// ---------------------------------------------------------------------------

export function bandFor(score: number): string {
  for (const b of BANDS) {
    if (score >= b.min) return b.key;
  }
  return "Poor Match";
}

function humanDateISO(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function humanPubDate(pubDate: string): string {
  const d = new Date(pubDate);
  if (isNaN(d.getTime())) return pubDate;
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
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

/** Render one job entry for the markdown report. */
export function renderEntry(rank: number, job: StoredJob): string {
  const meta: string[] = [];
  if (job.location) meta.push(`**${job.location}**`);
  if (job.rate) meta.push(`💰 ${job.rate}`);
  meta.push("[JOBSERVE]");
  meta.push(`posted ${humanPubDate(job.pubDate)}`);
  return [
    `### ${rank}. ${job.title}`,
    meta.join(" · "),
    "",
    "**Job description:**",
    "",
    job.description ? blockquote(job.description) : "> _Description not available._",
    "",
    `**Score: ${job.score}/10**`,
    "",
    job.reason || "_No reason provided._",
    "",
    "**Cover letter:**",
    "",
    job.coverLetter ? blockquote(job.coverLetter) : "> _Not generated._",
    "",
    `[View on JobServe](${job.link})`,
    "",
    "---",
    "",
    "",
  ].join("\n");
}

/** Build the full score-banded report for one date's jobs. */
export function buildBandedReport(date: string, jobs: StoredJob[]): string {
  const sorted = [...jobs].sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const aT = new Date(a.pubDate).getTime() || 0;
    const bT = new Date(b.pubDate).getTime() || 0;
    return bT - aT;
  });
  const scores = sorted.map((j) => j.score);
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  const top = scores.length ? Math.max(...scores) : 0;
  const counts = BANDS.map((b) => sorted.filter((j) => bandFor(j.score) === b.key).length);

  const lines: string[] = [];
  lines.push(`# JobServe RSS Jobs — ${humanDateISO(date)}`);
  lines.push("");
  lines.push(`**Source:** JobServe RSS feed (saved search). Jobs dated ${humanDateISO(date)}.`);
  lines.push(
    "Each entry has an LLM suitability score (0–10) against the candidate CV, a rank " +
      "reason, and a short cover letter. Re-running merges new feed items, skips jobs already " +
      "scored, and rebuilds this report sorted by score.",
  );
  lines.push("");
  lines.push("## Summary");
  lines.push("");
  lines.push(`- **Jobs ranked:** ${sorted.length}`);
  lines.push(`- **Average score:** ${avg.toFixed(1)}/10`);
  lines.push(`- **Highest score:** ${top.toFixed(1)}/10`);
  lines.push(`- **By band:** ${BANDS.map((b, i) => `${b.key} ${counts[i]}`).join(" · ")}`);
  lines.push("");

  let rank = 0;
  for (const band of BANDS) {
    const inBand = sorted.filter((j) => bandFor(j.score) === band.key);
    if (inBand.length === 0) continue;
    lines.push("---");
    lines.push("");
    lines.push(`## ${band.heading}`);
    lines.push(`*${inBand.length} role${inBand.length === 1 ? "" : "s"}*`);
    lines.push("");
    for (const job of inBand) {
      rank++;
      lines.push(renderEntry(rank, job));
    }
  }
  return lines.join("\n").trim() + "\n";
}

// ---------------------------------------------------------------------------
// RSS source
// ---------------------------------------------------------------------------

// JobServe RSS feeds are 200-300 KB; pass a generous cap so web_fetch's
// default (50 000 chars) does not silently truncate the feed mid-item.
const FEED_MAX_CHARS = 1_000_000;

async function readRssSource(clients: Clients, src: string): Promise<string> {
  if (/^https?:\/\//i.test(src)) {
    const res = await webFetch(clients, src, FEED_MAX_CHARS);
    if (!res || res.status_code >= 400) {
      throw new Error(`feed fetch failed (HTTP ${res?.status_code ?? "no response"})`);
    }
    return res.content ?? "";
  }
  return readFileSync(src, "utf-8");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

async function processFeed(
  _input: Record<string, unknown>,
  clients: Clients,
  profile: Record<string, unknown>,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const p = profile as Profile;
  const rssSource = p.rss_source ?? "";
  const cvPath = p.cv_path ?? "";
  const outputDir = (p.output_dir ?? ".").replace(/[\\/]+$/, "");
  const rankModel = p.rank_model ?? DEFAULT_RANK_MODEL;
  const maxJobs = p.max_jobs ?? 0;

  if (!rssSource) return { error: "profile.rss_source is not set." };
  if (!cvPath) return { error: "profile.cv_path is not set." };

  // --- CV -------------------------------------------------------------------
  const cvResolved = resolveOutputPath(cvPath, config);
  let cv: string;
  try {
    cv = readFileSync(cvResolved, "utf-8");
  } catch (err) {
    return { error: `Cannot read CV at ${cvResolved}: ${String(err)}` };
  }
  if (!cv.trim()) return { error: `CV file at ${cvResolved} is empty.` };

  // --- Feed -----------------------------------------------------------------
  let xml: string;
  try {
    xml = await readRssSource(clients, rssSource);
  } catch (err) {
    return { error: `Cannot read RSS source ${rssSource}: ${String(err)}` };
  }

  const items = parseRssItems(xml);
  console.error(`[jobserve_rss_processor] Parsed ${items.length} item(s) from feed`);
  if (items.length === 0) {
    return { message: "No <item> elements found in the RSS source.", jobs_added: 0 };
  }

  // Full cleaned description per guid — used to score new jobs and to backfill
  // the description onto jobs scored before this field was stored.
  const descByGuid = new Map<string, string>();
  for (const it of items) {
    const g = it.guid || it.link;
    if (g) descByGuid.set(g, cleanDescription(it.description));
  }

  // --- Group by pubDate date ------------------------------------------------
  const byDate = new Map<string, RssItem[]>();
  let skippedNoDate = 0;
  for (const it of items) {
    const date = pubDateToISO(it.pubDate);
    if (date === UNKNOWN_DATE) {
      skippedNoDate++;
      continue;
    }
    const list = byDate.get(date);
    if (list) list.push(it);
    else byDate.set(date, [it]);
  }

  // --- Rebuild each date's sidecar + report --------------------------------
  const seen = new Set<string>();
  const filesWritten: string[] = [];
  let added = 0;
  let alreadyPresent = 0;
  let topScore = 0;
  let capped = false;

  // Process newest dates first so a max_jobs cap deterministically spends its
  // budget on the most recent jobs rather than whatever order the feed emitted.
  const datesNewestFirst = [...byDate.entries()].sort(([a], [b]) => b.localeCompare(a));

  for (const [date, dateItems] of datesNewestFirst) {
    const mdPath = resolveOutputPath(`${outputDir}/${date}-js-rss-data.md`, config);
    const dataPath = resolveOutputPath(`${outputDir}/${date}-js-rss-data.json`, config);
    const existingDataRaw = readIfExists(dataPath);
    const existingJobs = parseSidecar(existingDataRaw);
    const existingGuids = new Set(existingJobs.map((j) => j.guid));

    // Refresh each job's description from the current feed where available.
    // description is mechanically derived from the RSS, so changes to
    // cleanDescription propagate on the next run with no re-scoring; the
    // LLM-produced fields (score, reason, coverLetter) are preserved.
    for (const ej of existingJobs) {
      const d = descByGuid.get(ej.guid);
      if (d) ej.description = d;
    }

    const newJobs: StoredJob[] = [];
    for (const item of dateItems) {
      const guid = item.guid || item.link;
      if (!guid) continue;
      if (existingGuids.has(guid) || seen.has(guid)) {
        alreadyPresent++;
        continue;
      }
      if (maxJobs > 0 && added >= maxJobs) {
        capped = true;
        break;
      }
      seen.add(guid);

      const job = enrich(item);
      console.error(`[jobserve_rss_processor] Scoring: ${job.title}`);
      const a = await assessJob(rankModel, cv, job);
      // Transient failure — skip storing so the next run retries this guid.
      if (a === null) {
        added++;
        continue;
      }
      newJobs.push({
        guid,
        title: job.title,
        link: job.link,
        location: job.location,
        rate: job.rate,
        pubDate: job.pubDate,
        score: a.score,
        reason: a.reason,
        coverLetter: a.coverLetter,
        description: job.description,
      });
      added++;
    }

    const merged = [...existingJobs, ...newJobs];
    if (merged.length === 0) {
      if (capped) break;
      continue;
    }
    for (const j of merged) topScore = Math.max(topScore, j.score);

    // Content-compare: write each file only if its rendered output differs
    // from what is already on disk. A re-run with nothing new touches no
    // files; a report-format change still re-renders without re-scoring.
    const dataContent = serializeSidecar(merged);
    const mdContent = buildBandedReport(date, merged);
    let changed = false;
    if (dataContent !== existingDataRaw) {
      filesWritten.push(await writeFile(dataPath, dataContent, config));
      changed = true;
    }
    if (mdContent !== readIfExists(mdPath)) {
      filesWritten.push(await writeFile(mdPath, mdContent, config));
      changed = true;
    }
    console.error(
      changed
        ? `[jobserve_rss_processor] ${date}: +${newJobs.length} new (${merged.length} total) — files updated`
        : `[jobserve_rss_processor] ${date}: ${merged.length} job(s) — unchanged, nothing written`,
    );
    if (capped) break;
  }

  return {
    feed_items: items.length,
    jobs_added: added,
    jobs_already_present: alreadyPresent,
    skipped_no_date: skippedNoDate,
    files_written: filesWritten,
    top_score: topScore,
    capped_at_max_jobs: capped,
  };
}

// ---------------------------------------------------------------------------
// Tool: search — query a date's sidecar by score
// ---------------------------------------------------------------------------

const DEFAULT_SEARCH_MAX_ITEMS = 50;

/** Filter to jobs scoring at or above `minScore`, sort by score descending
 *  (newest pubDate breaks ties), and cap to `maxItems`. Pure for testability. */
export function filterAndRankJobs(
  jobs: StoredJob[],
  options: { minScore?: number; maxItems?: number },
): StoredJob[] {
  const min = options.minScore ?? 0;
  const cap = options.maxItems ?? DEFAULT_SEARCH_MAX_ITEMS;
  return jobs
    .filter((j) => j.score >= min)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      const aT = new Date(a.pubDate).getTime() || 0;
      const bT = new Date(b.pubDate).getTime() || 0;
      return bT - aT;
    })
    .slice(0, cap);
}

async function search(
  input: Record<string, unknown>,
  _clients: Clients,
  profile: Record<string, unknown>,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const p = profile as Profile;
  const outputDir = (p.output_dir ?? ".").replace(/[\\/]+$/, "");
  const date = typeof input.date === "string" ? input.date : "";
  const minScore = typeof input.minScore === "number" ? input.minScore : 0;
  const maxItems =
    typeof input.maxItems === "number" && input.maxItems > 0
      ? Math.floor(input.maxItems)
      : DEFAULT_SEARCH_MAX_ITEMS;

  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return { error: `date must be a YYYY-MM-DD string; got ${JSON.stringify(input.date)}.` };
  }

  const dataPath = resolveOutputPath(`${outputDir}/${date}-js-rss-data.json`, config);
  const raw = readIfExists(dataPath);
  if (!raw) {
    return {
      date,
      data_path: dataPath,
      total_in_file: 0,
      returned: 0,
      jobs: [],
      message: `No sidecar at ${dataPath}.`,
    };
  }

  const all = parseSidecar(raw);
  const jobs = filterAndRankJobs(all, { minScore, maxItems });
  return {
    date,
    data_path: dataPath,
    total_in_file: all.length,
    returned: jobs.length,
    min_score: minScore,
    max_items: maxItems,
    jobs,
  };
}

// ---------------------------------------------------------------------------
// Exposed tools
// ---------------------------------------------------------------------------

export const TOOLS = defineTools([
  {
    name: "process_feed",
    description:
      "Reads job items from a JobServe RSS feed and rebuilds a score-banded " +
      "markdown report per date — each new job gets an LLM suitability score " +
      "(0-10), a rank reason, and a brief cover letter judged against a CV. " +
      "Idempotent: jobs already recorded are never re-scored.",
    inputSchema: {},
    handler: processFeed,
  },
  {
    name: "search",
    description:
      "Search saved JobServe job records for a given date. Reads the " +
      "YYYY-MM-DD-js-rss-data.json sidecar in the configured output_dir, " +
      "filters to jobs scoring at or above minScore, sorts by score descending, " +
      "and returns up to maxItems entries with full job data (title, link, " +
      "location, rate, score, reason, cover letter, description).",
    inputSchema: {
      date: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/, "date must be in YYYY-MM-DD format")
        .describe("Date of the sidecar file to read, in YYYY-MM-DD format."),
      minScore: z
        .number()
        .min(0)
        .max(10)
        .optional()
        .describe("Minimum job score (0-10) to include. Defaults to 0 (no floor)."),
      maxItems: z
        .number()
        .int()
        .positive()
        .optional()
        .describe(
          `Maximum number of jobs to return, ordered by score desc. Defaults to ${DEFAULT_SEARCH_MAX_ITEMS}.`,
        ),
    },
    handler: search,
  },
]);
