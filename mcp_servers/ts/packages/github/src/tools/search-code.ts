import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerSearchCode(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "search_code",
    {
      description:
        "Search for code across GitHub repositories. Returns matching files with context snippets. Note: limited to 10 requests/minute.",
      inputSchema: {
        query: z.string().min(1).describe("Search query (code keywords, symbols, etc.)"),
        repo: z.string().describe("Limit search to a repository in owner/repo format").optional(),
        language: z.string().describe("Filter by programming language (e.g. python, javascript)").optional(),
        maxResults: z.number().int().min(1).max(100).default(10).describe("Max results (default 10, max 100)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const maxResults = input.maxResults ?? 10;

      logger.info({ tool: "search_code", request_id: requestId }, "tool_call_start");

      try {
        const qParts = [input.query];
        if (input.repo) qParts.push(`repo:${input.repo}`);
        if (input.language) qParts.push(`language:${input.language}`);

        const resp = await octokit.search.code({
          q: qParts.join(" "),
          per_page: maxResults,
          headers: { Accept: "application/vnd.github.text-match+json" },
        });

        const items = resp.data.items;
        const total = resp.data.total_count;

        if (items.length === 0) {
          return { content: [{ type: "text" as const, text: "Code search: 0 results" }] };
        }

        const structured = items.map((item) => {
          const textMatches = (item as Record<string, unknown>).text_matches as Array<Record<string, unknown>> | undefined;
          let fragment = "";
          if (textMatches && textMatches.length > 0) {
            fragment = String(textMatches[0].fragment ?? "").trim();
            if (fragment.length > 200) fragment = fragment.slice(0, 200) + "...";
          }
          return {
            repo: item.repository?.full_name ?? "",
            path: item.path ?? "",
            url: item.html_url ?? "",
            fragment,
          };
        });

        const lines = [`Code search: ${items.length} of ${total} result(s)`, ""];
        structured.forEach((r, i) => {
          lines.push(`${i + 1}. ${r.repo} -- ${r.path}`);
          if (r.fragment) {
            for (const line of r.fragment.split("\n").slice(0, 4)) {
              lines.push(`   ${line}`);
            }
          }
          lines.push("");
        });

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "search_code", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: { results: structured, total_count: total },
          content: [{ type: "text" as const, text: lines.join("\n").trimEnd() }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "search_code", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error searching code: ${message}` }], isError: true };
      }
    },
  );
}
