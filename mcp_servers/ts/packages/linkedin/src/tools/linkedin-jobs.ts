import { z } from "zod";
import * as cheerio from "cheerio";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

const DATE_FILTER_MAP: Record<string, string> = {
  "24hr": "r86400",
  "past week": "r604800",
  "past month": "r2592000",
};

interface JobResult {
  index: number;
  title: string;
  company: string;
  location: string;
  posted: string;
  salary: string;
  url: string;
}

export function registerLinkedInJobs(server: McpServer, logger: Logger): void {
  server.registerTool(
    "linkedin_jobs",
    {
      description:
        "Search for job postings on LinkedIn. Returns job title, company, location, date, salary, and URL.",
      inputSchema: {
        keyword: z.string().min(1).describe("Job search keyword (e.g. 'software engineer')"),
        location: z.string().describe("Job location (e.g. 'New York', 'Remote')").optional(),
        dateSincePosted: z
          .enum(["past month", "past week", "24hr"])
          .describe("Recency filter")
          .optional(),
        jobType: z
          .enum(["full time", "part time", "contract", "temporary", "internship"])
          .describe("Employment type")
          .optional(),
        remoteFilter: z.enum(["on site", "remote", "hybrid"]).describe("Work arrangement").optional(),
        experienceLevel: z
          .enum(["internship", "entry level", "associate", "senior", "director", "executive"])
          .describe("Experience level")
          .optional(),
        limit: z.number().int().min(1).max(50).default(10).describe("Max number of results to return (default 10)").optional(),
        sortBy: z.enum(["recent", "relevant"]).describe("Sort order").optional(),
      },
      outputSchema: {
        jobs: z.array(
          z.object({
            index: z.number().int(),
            title: z.string(),
            company: z.string(),
            location: z.string(),
            posted: z.string(),
            salary: z.string(),
            url: z.string(),
          }),
        ),
        total_found: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const limit = input.limit ?? 10;

      logger.info({ tool: "linkedin_jobs", request_id: requestId, keyword: input.keyword }, "tool_call_start");

      try {
        const dateFilter = input.dateSincePosted ? DATE_FILTER_MAP[input.dateSincePosted] ?? "" : "";
        const sortParam = input.sortBy === "recent" ? "&sortBy=DD" : "";

        const encodedKeyword = encodeURIComponent(input.keyword);
        const encodedLocation = input.location ? encodeURIComponent(input.location) : "";

        let url =
          `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=${encodedKeyword}`;
        if (encodedLocation) url += `&location=${encodedLocation}`;
        if (dateFilter) url += `&f_TPR=${dateFilter}`;
        url += `&start=0&count=${limit}${sortParam}`;

        const response = await resilientFetch(url, {
          headers: { "User-Agent": USER_AGENT },
        }, { timeoutMs: 15_000, retries: 3 });

        if (response.status >= 400) {
          throw new UpstreamError(`HTTP ${response.status} from LinkedIn`, response.status);
        }

        const html = await response.text();
        const $ = cheerio.load(html);
        const cards = $("li");

        const jobs: JobResult[] = [];
        let cardIndex = 0;

        cards.each((_i, card) => {
          if (cardIndex >= limit) return false;

          const $card = $(card);
          const titleEl = $card.find("h3.base-search-card__title");
          const title = titleEl.text().trim();
          if (!title) return;

          const company = $card.find("h4.base-search-card__subtitle").text().trim();
          const location = $card.find("span.job-search-card__location").text().trim();
          const posted = $card.find("time").text().trim();
          const salary = $card.find("span.job-search-card__salary-info").text().trim() || "Not listed";
          const jobUrl = $card.find("a.base-card__full-link").attr("href") ?? "";

          cardIndex++;
          jobs.push({
            index: cardIndex,
            title: decodeHtmlEntities(title),
            company: decodeHtmlEntities(company),
            location: decodeHtmlEntities(location),
            posted,
            salary,
            url: jobUrl,
          });
        });

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "linkedin_jobs", request_id: requestId, duration_ms: durationMs, outcome: "success", result_count: jobs.length },
          "tool_call_end",
        );

        // Build text output matching Python format
        let textOutput: string;
        if (jobs.length === 0) {
          textOutput = "No job postings found matching your criteria.";
        } else {
          textOutput = jobs
            .map(
              (j) =>
                `${j.index}. ${j.title}\n` +
                `   Company: ${j.company}\n` +
                `   Location: ${j.location}\n` +
                `   Posted: ${j.posted}\n` +
                `   Salary: ${j.salary}\n` +
                `   URL: ${j.url}`,
            )
            .join("\n\n");
        }

        return {
          structuredContent: { jobs: jobs.map((j) => ({ ...j })), total_found: jobs.length },
          content: [{ type: "text" as const, text: textOutput }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "linkedin_jobs", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error searching LinkedIn jobs: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&#x2F;/g, "/");
}
