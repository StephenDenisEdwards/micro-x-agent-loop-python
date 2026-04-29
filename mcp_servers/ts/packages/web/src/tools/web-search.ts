import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { ValidationError, UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";

const BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search";
const TIMEOUT_MS = 30_000;
const DEFAULT_COUNT = 5;

interface SearchResult {
  title: string;
  url: string;
  description: string;
}

export function registerWebSearch(server: McpServer, logger: Logger, apiKey: string): void {
  server.registerTool(
    "web_search",
    {
      description:
        "Search the web and return a list of results with titles, URLs, and descriptions. " +
        "Use this to discover URLs before fetching their full content with web_fetch.",
      inputSchema: {
        query: z.string().min(1).max(400).describe("Search query (max 400 characters)"),
        count: z
          .number()
          .int()
          .min(1)
          .max(20)
          .default(DEFAULT_COUNT)
          .describe(`Number of results to return (1–20, default ${DEFAULT_COUNT})`)
          .optional(),
      },
      outputSchema: {
        query: z.string(),
        results: z.array(
          z.object({
            title: z.string(),
            url: z.string(),
            description: z.string(),
          }),
        ),
        total_results: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const count = input.count ?? DEFAULT_COUNT;

      logger.info({ tool: "web_search", request_id: requestId, query: input.query }, "tool_call_start");

      try {
        if (!input.query.trim()) {
          throw new ValidationError("query must not be empty");
        }

        const query = input.query.slice(0, 400);

        // Call Brave Search API
        const url = new URL(BRAVE_SEARCH_URL);
        url.searchParams.set("q", query);
        url.searchParams.set("count", String(count));

        const response = await resilientFetch(url.toString(), {
          headers: {
            "X-Subscription-Token": apiKey,
            "Accept": "application/json",
          },
        }, { timeoutMs: TIMEOUT_MS, retries: 3 });

        if (response.status >= 400) {
          throw new UpstreamError(`HTTP ${response.status} from Brave Search API`, response.status);
        }

        const data = (await response.json()) as Record<string, unknown>;
        const webData = data.web as Record<string, unknown> | undefined;
        const rawResults = (webData?.results ?? []) as Array<Record<string, unknown>>;

        const results: SearchResult[] = rawResults.map((r) => ({
          title: String(r.title ?? "(no title)"),
          url: String(r.url ?? ""),
          description: String(r.description ?? ""),
        }));

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "web_search", request_id: requestId, duration_ms: durationMs, outcome: "success", result_count: results.length },
          "tool_call_end",
        );

        // Build text output (matching Python format)
        const textParts: string[] = [];
        if (results.length === 0) {
          textParts.push(`No results found for: ${query}`);
        } else {
          textParts.push(`Search: "${query}"`);
          textParts.push(`Results: ${results.length}`);
          textParts.push("");
          results.forEach((r, i) => {
            textParts.push(`${i + 1}. ${r.title}`);
            textParts.push(`   ${r.url}`);
            if (r.description) textParts.push(`   ${r.description}`);
            textParts.push("");
          });
        }

        const structured = {
          query,
          results,
          total_results: results.length,
        };

        return {
          structuredContent: { ...structured, results: [...results.map((r) => ({ ...r }))] },
          content: [{ type: "text" as const, text: textParts.join("\n").trimEnd() }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);
        const errorCode =
          err instanceof ValidationError ? "validation_error" : err instanceof UpstreamError ? "upstream_error" : "internal_error";

        logger.error(
          { tool: "web_search", request_id: requestId, duration_ms: durationMs, outcome: "error", error_code: errorCode, error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
