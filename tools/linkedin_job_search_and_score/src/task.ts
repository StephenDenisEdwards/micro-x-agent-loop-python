import { z } from "zod";
import type { Clients } from "./tools.js";
import { linkedinSearch, linkedinDetail, fsRead } from "./tools.js";
import { writeFile, resolveOutputPath } from "../../_runtime/src/utils.js";
import { createMessage } from "../../_runtime/src/llm.js";
import { readFileSync } from "node:fs";

export const SERVERS = ["linkedin", "filesystem"];

export const TOOL_NAME = "linkedin_job_search_and_score";
export const TOOL_DESCRIPTION = "Search LinkedIn for jobs matching configured keywords and score them against a CV.";

export const TOOL_INPUT_SCHEMA = {
  date_filter: z
    .enum(["24hr", "past week", "past month"])
    .default("past week")
    .describe("Date posted filter for LinkedIn job search"),
};

interface JobOutput {
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

interface ScoredJob {
  url: string;
  title: string;
  company: string;
  location: string;
  salary: string;
  posted: string;
  description: string;
  score: number;
  reason: string;
  coverLetter: string;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithRetry(
  clients: Clients,
  url: string,
  retries = 3,
  delayMs = 2000,
): Promise<{ title: string; company: string; location: string; description: string; url: string } | null> {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const detail = await linkedinDetail(clients, url);
      if (detail) return detail;
      await sleep(delayMs * (attempt + 1));
    } catch (err) {
      console.error(`Attempt ${attempt + 1} failed for ${url}:`, err);
      if (attempt < retries - 1) await sleep(delayMs * (attempt + 1));
    }
  }
  return null;
}

async function scoreJob(
  cvText: string,
  jobTitle: string,
  jobDescription: string,
  model: string,
  coverLetterMaxChars: number,
): Promise<{ score: number; reason: string; coverLetter: string }> {
  const prompt = `You are a job-matching assistant. Score how well this job matches the candidate's CV.

CV:
${cvText.slice(0, 3000)}

Job Title: ${jobTitle}
Job Description:
${jobDescription.slice(0, 2000)}

Respond ONLY with valid JSON (no markdown, no extra text):
{
  "score": <integer 0-10>,
  "reason": "<2-3 sentence explanation of the match quality>",
  "coverLetter": "<personalised cover letter max ${coverLetterMaxChars} chars referencing specific CV achievements>"
}`;

  // Budget enough output tokens for the cover letter (~1 token ≈ 3-4 chars)
  // plus the score/reason and JSON scaffolding, with a sane floor.
  const maxTokens = Math.max(512, Math.ceil(coverLetterMaxChars / 3) + 400);

  const [text] = await createMessage(
    model,
    maxTokens,
    [{ role: "user", content: prompt }],
    { temperature: 0.3 },
  );

  try {
    const cleaned = text.replace(/```json\n?/g, "").replace(/```\n?/g, "").trim();
    const parsed = JSON.parse(cleaned) as { score: number; reason: string; coverLetter: string };
    return {
      score: Math.min(10, Math.max(0, Math.round(Number(parsed.score)))),
      reason: String(parsed.reason ?? "").slice(0, 500),
      coverLetter: String(parsed.coverLetter ?? "").slice(0, coverLetterMaxChars),
    };
  } catch {
    console.error("Failed to parse LLM response:", text.slice(0, 200));
    return { score: 0, reason: "Failed to score job.", coverLetter: "" };
  }
}

/**
 * Load previously-scored jobs from the output file so a re-run can skip jobs
 * it has already ranked. Returns [] when the file does not exist yet (first
 * run). Throws if the file exists but is not a JSON array — the caller refuses
 * to overwrite in that case rather than silently clobber prior results.
 */
function loadExistingOutput(resolvedPath: string): JobOutput[] {
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
  return parsed as JobOutput[];
}

export async function handleTool(
  input: { date_filter: "24hr" | "past week" | "past month" },
  clients: Clients,
  profile: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const cvPath = String(profile["cv_path"] ?? "");
  const outputPath = String(profile["output_path"] ?? "jobs_output.json");
  const jobTypes = (profile["job_types"] as string[] | undefined) ?? ["contract"];
  const location = String(profile["location"] ?? "United Kingdom");
  const keywords = (profile["keywords"] as string[] | undefined) ?? [];
  const batchSize = Number(profile["batch_size"] ?? 5);
  const limitPerKeyword = Number(profile["limit_per_keyword"] ?? 20);
  const rankModel = String(profile["rank_model"] ?? "anthropic/claude-haiku-4-5-20251001");
  const coverLetterMaxChars = Number(profile["cover_letter_max_chars"] ?? 1500);
  const searchUrlBase = String(profile["search_url_base"] ?? "");

  if (!cvPath) throw new Error("cv_path is required in profile.json");
  if (keywords.length === 0) throw new Error("keywords array is required in profile.json");

  console.error(`Reading CV from: ${cvPath}`);
  const cvText = await fsRead(clients, cvPath);
  if (!cvText) throw new Error(`Could not read CV from path: ${cvPath}`);
  console.error(`CV loaded (${cvText.length} chars)`);

  const seenUrls = new Set<string>();
  const collectedJobs: Array<{
    url: string;
    title: string;
    company: string;
    location: string;
    salary: string;
    posted: string;
  }> = [];

  for (const keyword of keywords) {
    for (const jobType of jobTypes) {
      console.error(`Searching: "${keyword}" | type: ${jobType} | filter: ${input.date_filter}`);
      try {
        const validJobType = jobType as "full time" | "part time" | "contract" | "temporary" | "internship";
        const results = await linkedinSearch(clients, keyword, {
          location,
          dateSincePosted: input.date_filter,
          jobType: validJobType,
          limit: limitPerKeyword,
          sortBy: "recent",
          ...(searchUrlBase ? { searchUrlBase } : {}),
        });

        let newCount = 0;
        for (const job of results) {
          const url = String(job["url"] ?? "");
          if (!url || seenUrls.has(url)) continue;
          seenUrls.add(url);
          newCount++;
          collectedJobs.push({
            url,
            title: String(job["title"] ?? ""),
            company: String(job["company"] ?? ""),
            location: String(job["location"] ?? ""),
            salary: String(job["salary"] ?? ""),
            posted: String(job["posted"] ?? ""),
          });
        }
        console.error(`  Found ${results.length} results, ${newCount} new (total: ${collectedJobs.length})`);
      } catch (err) {
        console.error(`  Search failed for "${keyword}":`, err);
      }
      await sleep(1000);
    }
  }

  // Incremental scoring: load any jobs already in the output file and skip
  // them — no detail fetch, no LLM call, no duplicate row. Refuse to run if the
  // existing file is unreadable-as-array, to avoid clobbering it.
  const resolvedOutput = resolveOutputPath(outputPath, {});
  let existing: JobOutput[];
  try {
    existing = loadExistingOutput(resolvedOutput);
  } catch (err) {
    throw new Error(`Existing output at ${outputPath} could not be parsed (${err}). Refusing to overwrite.`);
  }
  const existingByUrl = new Map<string, JobOutput>();
  for (const j of existing) {
    const key = j.guid || j.link;
    if (key) existingByUrl.set(key, j);
  }

  const toScore = collectedJobs.filter((j) => !existingByUrl.has(j.url));
  const skipped = collectedJobs.length - toScore.length;
  console.error(
    `\n${collectedJobs.length} unique jobs found: ${skipped} already scored, ${toScore.length} to score.`,
  );

  const scoredJobs: ScoredJob[] = [];

  for (let i = 0; i < toScore.length; i += batchSize) {
    const batch = toScore.slice(i, i + batchSize);
    console.error(`Fetching details batch ${Math.floor(i / batchSize) + 1}/${Math.ceil(toScore.length / batchSize)} (${batch.length} jobs)...`);

    const detailResults = await Promise.all(
      batch.map(async (job) => {
        const detail = await fetchWithRetry(clients, job.url);
        return { job, detail };
      }),
    );

    for (const { job, detail } of detailResults) {
      if (!detail) {
        console.error(`  Skipping ${job.url} — could not fetch details`);
        continue;
      }

      const description = detail.description ?? "";
      console.error(`  Scoring: ${detail.title} @ ${detail.company}`);

      const { score, reason, coverLetter } = await scoreJob(cvText, detail.title, description, rankModel, coverLetterMaxChars);

      scoredJobs.push({
        url: job.url,
        title: detail.title,
        company: detail.company,
        location: detail.location || job.location,
        salary: job.salary,
        posted: job.posted,
        description,
        score,
        reason,
        coverLetter,
      });
    }

    if (i + batchSize < toScore.length) {
      await sleep(2000);
    }
  }

  const now = new Date();
  const newOutput: JobOutput[] = scoredJobs.map((j) => ({
    guid: j.url,
    title: j.title,
    link: j.url,
    location: j.location,
    rate: j.salary,
    pubDate: now.toUTCString(),
    score: j.score,
    reason: j.reason,
    coverLetter: j.coverLetter,
    description: j.description,
  }));

  // Merge newly-scored jobs with the kept existing ones (no key overlap — those
  // were filtered out above), then sort the whole file by score.
  const merged = [...existingByUrl.values(), ...newOutput];
  merged.sort((a, b) => b.score - a.score);

  const jsonContent = JSON.stringify(merged, null, 2);
  const resolvedPath = await writeFile(resolvedOutput, jsonContent, {});
  console.error(`\nWrote ${merged.length} jobs (${newOutput.length} new) to: ${resolvedPath}`);

  const topJobs = merged.slice(0, 5).map((j) => ({
    title: j.title,
    location: j.location,
    score: j.score,
    link: j.link,
  }));

  return {
    success: true,
    total_found: collectedJobs.length,
    newly_scored: newOutput.length,
    skipped_existing: skipped,
    total_in_file: merged.length,
    output_path: resolvedPath,
    top_jobs: topJobs,
  };
}