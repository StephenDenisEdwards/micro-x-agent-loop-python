import { z } from "zod";
import * as cheerio from "cheerio";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError } from "@micro-x/mcp-shared";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

const HEADERS: Record<string, string> = {
  "User-Agent": USER_AGENT,
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.5",
};

export function registerLinkedInJobDetail(server: McpServer, logger: Logger): void {
  server.registerTool(
    "linkedin_job_detail",
    {
      description:
        "Fetch the full job specification/description from a LinkedIn job URL. " +
        "Use this after linkedin_jobs to get complete details for a specific posting.",
      inputSchema: {
        url: z
          .string()
          .min(1)
          .describe("The LinkedIn job URL (e.g. from a linkedin_jobs search result)"),
      },
      outputSchema: {
        title: z.string(),
        company: z.string(),
        location: z.string(),
        description: z.string(),
        url: z.string(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "linkedin_job_detail", request_id: requestId, url: input.url }, "tool_call_start");

      try {
        const response = await fetch(input.url, { headers: HEADERS });

        if (response.status !== 200) {
          throw new UpstreamError(`HTTP ${response.status} fetching job page`, response.status);
        }

        const html = await response.text();
        const $ = cheerio.load(html);

        const title = ($("h1.top-card-layout__title").text() || $("h1").first().text()).trim();
        const company = (
          $("a.topcard__org-name-link").text() ||
          $(".top-card-layout__company-name").text()
        ).trim();
        const location = (
          $("span.topcard__flavor--bullet").text() ||
          $("span.top-card-layout__bullet").text()
        ).trim();

        // Find the description container
        const descEl =
          $(".description__text").first() ||
          $(".show-more-less-html__markup").first() ||
          $(".decorated-job-posting__details").first();

        let description = "";
        if (descEl.length) {
          description = htmlToText($, descEl);
        }

        if (!description.trim()) {
          const durationMs = Date.now() - startTime;
          logger.warn(
            { tool: "linkedin_job_detail", request_id: requestId, duration_ms: durationMs },
            "could_not_extract_description",
          );

          return {
            content: [
              {
                type: "text" as const,
                text:
                  "Could not extract job description from the page. " +
                  "LinkedIn may have blocked the request or the page structure has changed.",
              },
            ],
            isError: true,
          };
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "linkedin_job_detail", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        // Build text output matching Python format
        const textParts: string[] = [];
        if (title) textParts.push(`Title: ${title}`);
        if (company) textParts.push(`Company: ${company}`);
        if (location) textParts.push(`Location: ${location}`);
        textParts.push("");
        textParts.push("--- Job Description ---");
        textParts.push("");
        textParts.push(description);

        const structured = {
          title,
          company,
          location,
          description,
          url: input.url,
        };

        return {
          structuredContent: { ...structured },
          content: [{ type: "text" as const, text: textParts.join("\n") }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "linkedin_job_detail", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching job details: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

/**
 * Simple HTML-to-text conversion for job descriptions.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function htmlToText($: cheerio.CheerioAPI, el: cheerio.Cheerio<any>): string {
  // Remove script/style
  el.find("script, style").remove();

  // Replace <br> with newlines
  el.find("br").replaceWith("\n");

  // Add newlines around block elements
  el.find("p, div, tr, h1, h2, h3, h4, h5, h6, blockquote").each((_i, node) => {
    $(node).prepend("\n");
    $(node).append("\n");
  });

  // Bullet list items
  el.find("li").each((_i, node) => {
    $(node).prepend("\n- ");
  });

  let text = el.text();

  // Normalize whitespace
  text = text.replace(/\t+/g, "  ");
  text = text.replace(/ {3,}/g, "  ");
  text = text.replace(/\n{3,}/g, "\n\n");

  return text.trim();
}
