import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerListPRs(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "list_prs",
    {
      description:
        "List pull requests for a GitHub repository. If repo is omitted, lists PRs authored by you across all repos.",
      inputSchema: {
        repo: z.string().describe("Repository in owner/repo format. If omitted, lists your PRs across all repos.").optional(),
        state: z.enum(["open", "closed", "all"]).default("open").describe("Filter by state (default: open)").optional(),
        author: z.string().describe("Filter by author username").optional(),
        maxResults: z.number().int().min(1).max(100).default(10).describe("Max results (default 10, max 100)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const state = input.state ?? "open";
      const maxResults = input.maxResults ?? 10;

      logger.info({ tool: "list_prs", request_id: requestId }, "tool_call_start");

      try {
        let prs: Array<Record<string, unknown>>;
        let header: string;

        if (input.repo && !input.author) {
          const [owner, repo] = input.repo.split("/");
          const resp = await octokit.pulls.list({ owner, repo, state, per_page: maxResults });
          prs = resp.data as unknown as Array<Record<string, unknown>>;
          header = `PRs (${state}) for ${input.repo}: ${prs.length} result(s)`;
        } else {
          // Use search API
          const qParts = ["type:pr"];
          if (input.repo) qParts.push(`repo:${input.repo}`);
          qParts.push(input.author ? `author:${input.author}` : "author:@me");
          if (state !== "all") qParts.push(`state:${state}`);

          const resp = await octokit.search.issuesAndPullRequests({
            q: qParts.join(" "),
            per_page: maxResults,
            sort: "updated",
          });
          prs = resp.data.items as unknown as Array<Record<string, unknown>>;
          header = `PRs (${state}): ${prs.length} of ${resp.data.total_count} result(s)`;
        }

        const structured = prs.map((pr) => ({
          number: pr.number as number,
          title: (pr.title as string) ?? "",
          author: ((pr.user as Record<string, unknown>)?.login as string) ?? "unknown",
          state: (pr.state as string) ?? state,
          updated: ((pr.updated_at as string) ?? "").slice(0, 10),
          url: (pr.html_url as string) ?? "",
        }));

        const lines = [header, ""];
        structured.forEach((r, i) => {
          lines.push(`${i + 1}. #${r.number} — ${r.title}`);
          lines.push(`   Author: ${r.author} | Updated: ${r.updated}`);
          if (r.url) lines.push(`   ${r.url}`);
          lines.push("");
        });

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "list_prs", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: { prs: structured },
          content: [{ type: "text" as const, text: lines.join("\n").trimEnd() || "No pull requests found." }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "list_prs", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error", error_message: message }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error listing PRs: ${message}` }], isError: true };
      }
    },
  );
}
