import { z } from "zod";
import { defineTools } from "../../_runtime/src/tool-def.js";
import type { Clients } from "./tools.js";
import { linkedinSearch, linkedinDetail } from "./tools.js";
import { writeFile, resolveOutputPath } from "../../_runtime/src/utils.js";
import { createMessage } from "../../_runtime/src/llm.js";
import { readFileSync } from "node:fs";

export const SERVERS: string[] = ["linkedin"];

interface Profile {
  job_types: string[];
  location: string;
  keywords: string[];
  limit_per_keyword: number;
  urls_output_path: string;
  cv_path: string;
  output_path: string;
  batch_size: number;
  cover_letter_max_chars: number;
  rank_model: string;
  search_url_base: string;
}

type LinkedinJobType = "full time" | "part time" | "contract" | "temporary" | "internship";
type DateFilter = "24hr" | "past week" | "past month";

function mapJobType(jt: string): LinkedinJobType | undefined {
  const map: Record<string, LinkedinJobType> = {
    "contract": "contract",
    "full time": "full time",
    "part time": "part time",
    "temporary": "temporary",
    "internship": "internship",
  };
  return map[jt.toLowerCase()];
}

/**
 * Intermediate record written by run_search and consumed by score_save.
 * Carries the search-time metadata (salary, posted date) that the detail
 * endpoint does not return, so it survives the pipeline into the final output.
 */
interface JobRecord {
  url: string;
  title: string;
  company: string;
  location: string;
  salary: string;
  posted: string;
}

interface ScoredJob {
  guid: string;
  title: string;
  link: string;
  location: string;
  rate: string;
  pubDate: string;
  score: number;
  reason: string;
  coverLetter: string;
  description: string;
}

async function scoreJob(
  url: string,
  title: string,
  company: string,
  location: string,
  salary: string,
  posted: string,
  description: string,
  cvText: string,
  model: string,
  coverLetterMaxChars: number,
): Promise<{ score: number; reason: string; coverLetter: string }> {
  const prompt = `You are a job fit evaluator. Given a CV and a job description, score the fit 0-10 and write a cover letter.

CV:
${cvText.slice(0, 4000)}

Job Title: ${title}
Company: ${company}
Location: ${location}
Salary/Rate: ${salary}
Description:
${description.slice(0, 3000)}

Respond in this exact JSON format (no markdown, no extra text):
{
  "score": <integer 0-10>,
  "reason": "<2-3 sentence explanation of fit based on tech stack, seniority, domain, location>",
  "coverLetter": "<personalized cover letter max ${coverLetterMaxChars} chars referencing CV achievements>"
}`;

  const [text] = await createMessage(
    model,
    1500,
    [{ role: "user", content: prompt }],
    { temperature: 0.3 },
  );

  try {
    const cleaned = text.replace(/^```json\s*/i, "").replace(/```\s*$/, "").trim();
    const parsed = JSON.parse(cleaned) as { score: number; reason: string; coverLetter: string };
    return {
      score: Math.min(10, Math.max(0, Math.round(parsed.score))),
      reason: parsed.reason ?? "",
      coverLetter: (parsed.coverLetter ?? "").slice(0, coverLetterMaxChars),
    };
  } catch {
    console.error("Failed to parse LLM response:", text.slice(0, 200));
    return { score: 0, reason: "Could not parse scoring response.", coverLetter: "" };
  }
}

function extractProfile(profile: Record<string, unknown>): Profile {
  return {
    job_types: (profile["job_types"] as string[]) ?? [],
    location: String(profile["location"] ?? "United Kingdom"),
    keywords: (profile["keywords"] as string[]) ?? [],
    limit_per_keyword: Number(profile["limit_per_keyword"] ?? 20),
    urls_output_path: String(profile["urls_output_path"] ?? "job_urls.json"),
    cv_path: String(profile["cv_path"] ?? "cv.txt"),
    output_path: String(profile["output_path"] ?? "scored_jobs.json"),
    batch_size: Number(profile["batch_size"] ?? 5),
    cover_letter_max_chars: Number(profile["cover_letter_max_chars"] ?? 1500),
    rank_model: String(profile["rank_model"] ?? "anthropic/claude-haiku-4-5-20251001"),
    search_url_base: String(profile["search_url_base"] ?? ""),
  };
}

/** Coerce one entry (a URL string or a partial JobRecord) into a JobRecord. */
function toJobRecord(e: unknown): JobRecord | null {
  if (typeof e === "string") {
    return { url: e, title: "", company: "", location: "", salary: "", posted: "" };
  }
  if (e && typeof e === "object" && typeof (e as JobRecord).url === "string") {
    const r = e as Partial<JobRecord>;
    return {
      url: r.url as string,
      title: r.title ?? "",
      company: r.company ?? "",
      location: r.location ?? "",
      salary: r.salary ?? "",
      posted: r.posted ?? "",
    };
  }
  return null;
}

/**
 * Normalise a parsed URL/record file into a deduped JobRecord[]. Accepts:
 *   - a flat array of JobRecord objects (run_search output),
 *   - a flat array of plain URL strings (legacy),
 *   - an object grouping arrays of either under category keys, e.g.
 *     { "ai_fulltime": ["https://...", ...], "dotnet_contract": [...] }.
 */
function toJobRecords(raw: unknown): JobRecord[] {
  let entries: unknown[];
  if (Array.isArray(raw)) {
    entries = raw;
  } else if (raw && typeof raw === "object") {
    entries = Object.values(raw as Record<string, unknown>).flatMap((v) =>
      Array.isArray(v) ? v : [],
    );
  } else {
    entries = [];
  }

  const byUrl = new Map<string, JobRecord>();
  for (const e of entries) {
    const rec = toJobRecord(e);
    if (rec && rec.url && !byUrl.has(rec.url)) byUrl.set(rec.url, rec);
  }
  return Array.from(byUrl.values());
}

/**
 * Load previously-scored jobs from the output file so a re-run can skip jobs
 * it has already ranked. Returns [] when the file does not exist yet (first
 * run). Throws if the file exists but is not a JSON array — the caller refuses
 * to overwrite in that case rather than silently clobber prior results.
 */
function loadExistingScored(resolvedPath: string): ScoredJob[] {
  let raw: string;
  try {
    raw = readFileSync(resolvedPath, "utf8");
  } catch {
    return [];
  }
  const parsed = JSON.parse(raw) as unknown;
  if (!Array.isArray(parsed)) {
    throw new Error("existing output is not a JSON array");
  }
  return parsed as ScoredJob[];
}

export const TOOLS = defineTools([
  {
    name: "run_search",
    description: "Search LinkedIn for jobs based on profile keywords and output unique URLs to a JSON file.",
    inputSchema: {
      date_filter: z
        .enum(["24hr", "past week", "past month"])
        .default("past week")
        .describe('Date posted filter: "24hr", "past week", or "past month"'),
    },
    handler: async (
      input,
      clients: Clients,
      profile: Record<string, unknown>,
      config: Record<string, unknown>,
    ) => {
      const p = extractProfile(profile);
      const dateFilter = input.date_filter as DateFilter;

      // When no job types are configured, run a single (unfiltered) search per
      // keyword. Otherwise search each keyword once per configured type.
      const jobTypeFilters: (LinkedinJobType | undefined)[] =
        p.job_types.length > 0 ? p.job_types.map(mapJobType) : [undefined];

      // Dedupe by URL, keeping the first hit's search-time metadata.
      const byUrl = new Map<string, JobRecord>();

      for (const keyword of p.keywords) {
        console.error(`Searching keyword: "${keyword}"`);
        for (const mapped of jobTypeFilters) {
          const label = mapped ?? "any";
          try {
            const jobs = await linkedinSearch(clients, keyword, {
              location: p.location,
              dateSincePosted: dateFilter,
              limit: p.limit_per_keyword,
              sortBy: "recent",
              ...(mapped ? { jobType: mapped } : {}),
              ...(p.search_url_base ? { searchUrlBase: p.search_url_base } : {}),
            });
            for (const job of jobs) {
              if (job.url && !byUrl.has(job.url)) {
                byUrl.set(job.url, {
                  url: job.url,
                  title: job.title ?? "",
                  company: job.company ?? "",
                  location: job.location ?? "",
                  salary: job.salary ?? "",
                  posted: job.posted ?? "",
                });
              }
            }
            console.error(`  Found ${jobs.length} jobs for "${keyword}" / ${label}`);
          } catch (err) {
            console.error(`  Error searching "${keyword}" / ${label}:`, err);
          }
          await new Promise((r) => setTimeout(r, 1000));
        }
      }

      const records = Array.from(byUrl.values());
      const resolved = await writeFile(p.urls_output_path, JSON.stringify(records, null, 2), config);
      console.error(`Wrote ${records.length} unique jobs to ${resolved}`);

      return {
        success: true,
        message: `Found ${records.length} unique jobs across ${p.keywords.length} keywords.`,
        count: records.length,
        output_path: p.urls_output_path,
      };
    },
  },
  {
    name: "score_save",
    description: "Fetch job details for a list of LinkedIn URLs, score against CV, generate cover letters, and save JSON.",
    inputSchema: {
      urls_input_path: z
        .string()
        .describe(
          "Path to a JSON file of LinkedIn job URLs to score. Accepts run_search's job-record array, a flat array of URL strings, or an object grouping URL arrays under category keys.",
        ),
    },
    handler: async (input, clients: Clients, profile: Record<string, unknown>, config: Record<string, unknown>) => {
      const p = extractProfile(profile);
      const { urls_input_path } = input as { urls_input_path: string };

      let rawEntries: unknown;
      try {
        const resolvedInput = resolveOutputPath(urls_input_path, config);
        rawEntries = JSON.parse(readFileSync(resolvedInput, "utf8"));
      } catch (err) {
        throw new Error(`Failed to read URLs from ${urls_input_path}: ${err}`);
      }

      const records = toJobRecords(rawEntries);
      if (records.length === 0) {
        return { success: false, message: "No usable job URLs found in input file.", count: 0 };
      }

      // The CV is essential for meaningful scoring — fail loudly rather than
      // scoring every job against an empty CV and reporting success.
      let cvText: string;
      try {
        const resolvedCv = resolveOutputPath(p.cv_path, config);
        cvText = readFileSync(resolvedCv, "utf8");
      } catch (err) {
        return {
          success: false,
          message: `Could not read CV from ${p.cv_path}: ${err}. Scoring aborted.`,
          count: 0,
        };
      }
      if (cvText.trim().length === 0) {
        return {
          success: false,
          message: `CV at ${p.cv_path} is empty. Scoring aborted.`,
          count: 0,
        };
      }

      // Incremental scoring: load any jobs already in the output file and skip
      // them — no detail fetch, no LLM call, no duplicate row. Refuse to run if
      // the existing file is unreadable-as-array, to avoid clobbering it.
      const resolvedOutput = resolveOutputPath(p.output_path, config);
      let existing: ScoredJob[];
      try {
        existing = loadExistingScored(resolvedOutput);
      } catch (err) {
        return {
          success: false,
          message: `Existing output at ${p.output_path} could not be parsed (${err}). Refusing to overwrite.`,
          count: 0,
        };
      }
      const existingByUrl = new Map<string, ScoredJob>();
      for (const j of existing) {
        const key = j.guid || j.link;
        if (key) existingByUrl.set(key, j);
      }

      const toScore = records.filter((r) => !existingByUrl.has(r.url));
      const skipped = records.length - toScore.length;
      console.error(
        `${records.length} input jobs: ${skipped} already scored, ${toScore.length} to score.`,
      );

      const model: string = p.rank_model;
      const batchSize: number = p.batch_size;
      const coverLetterMaxChars: number = p.cover_letter_max_chars;
      const scoredJobs: ScoredJob[] = [];
      let processed = 0;

      for (let i = 0; i < toScore.length; i += batchSize) {
        const batch = toScore.slice(i, i + batchSize);
        console.error(
          `Processing batch ${Math.floor(i / batchSize) + 1} / ${Math.ceil(toScore.length / batchSize)} (${batch.length} jobs)`,
        );

        const results = await Promise.allSettled(
          batch.map(async (rec) => {
            const detail = await linkedinDetail(clients, rec.url);
            if (!detail) {
              console.error(`  Skipping ${rec.url} — could not fetch details`);
              return null;
            }

            const { score, reason, coverLetter } = await scoreJob(
              rec.url,
              detail.title,
              detail.company,
              detail.location,
              rec.salary,
              rec.posted || new Date().toUTCString(),
              detail.description,
              cvText,
              model,
              coverLetterMaxChars,
            );

            const job: ScoredJob = {
              guid: rec.url,
              title: detail.title,
              link: rec.url,
              location: detail.location,
              rate: rec.salary,
              pubDate: rec.posted,
              score,
              reason,
              coverLetter,
              description: detail.description,
            };
            console.error(`  Scored "${detail.title}" at ${detail.company}: ${score}/10`);
            return job;
          }),
        );

        for (const result of results) {
          if (result.status === "fulfilled" && result.value !== null) {
            scoredJobs.push(result.value);
            processed++;
          }
        }

        if (i + batchSize < toScore.length) {
          await new Promise((r) => setTimeout(r, 2000));
        }
      }

      // Merge newly-scored jobs with the kept existing ones (no key overlap —
      // collisions were filtered out above), then sort the whole file by score.
      const merged = [...existingByUrl.values(), ...scoredJobs];
      merged.sort((a, b) => b.score - a.score);

      const written = await writeFile(p.output_path, JSON.stringify(merged, null, 2), config);
      console.error(`Saved ${merged.length} scored jobs (${processed} new) to ${written}`);

      const avgScore =
        merged.length > 0
          ? (merged.reduce((s, j) => s + j.score, 0) / merged.length).toFixed(2)
          : "N/A";
      const topJobs = merged
        .slice(0, 3)
        .map((j) => `"${j.title}" (${j.score}/10)`)
        .join(", ");

      return {
        success: true,
        message: `Scored ${processed} new job(s); skipped ${skipped} already in output. Total in file: ${merged.length}. Avg score: ${avgScore}. Top: ${topJobs || "none"}.`,
        total_input: records.length,
        newly_scored: processed,
        skipped_existing: skipped,
        total_in_file: merged.length,
        average_score: avgScore,
        output_path: p.output_path,
      };
    },
  },
]);