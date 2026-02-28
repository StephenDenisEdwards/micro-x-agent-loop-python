import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerListIssues(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "list_issues",
    {
      description: "List or search issues in a GitHub repository. If repo is omitted or a query is provided, uses GitHub search.",
      inputSchema: {
        repo: z.string().describe("Repository in owner/repo format").optional(),
        state: z.enum(["open", "closed", "all"]).default("open").describe("Filter by state (default: open)").optional(),
        labels: z.string().describe("Comma-separated label names to filter by").optional(),
        query: z.string().describe("Search query (GitHub search syntax)").optional(),
        maxResults: z.number().int().min(1).max(30).default(10).describe("Max results (default 10, max 30)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const state = input.state ?? "open";
      const maxResults = input.maxResults ?? 10;

      logger.info({ tool: "list_issues", request_id: requestId }, "tool_call_start");

      try {
        if (input.query || !input.repo) {
          // Use search API
          const qParts = ["type:issue"];
          if (input.repo) qParts.push(`repo:${input.repo}`);
          if (state !== "all") qParts.push(`state:${state}`);
          if (input.labels) {
            for (const label of input.labels.split(",").map((l) => l.trim()).filter(Boolean)) {
              qParts.push(`label:"${label}"`);
            }
          }
          if (input.query) qParts.push(input.query);

          const resp = await octokit.search.issuesAndPullRequests({
            q: qParts.join(" "),
            per_page: maxResults,
            sort: "updated",
          });

          const items = resp.data.items;
          const header = `Issues (${state}): ${items.length} of ${resp.data.total_count} result(s)`;
          return { content: [{ type: "text" as const, text: formatIssues(header, items) }] };
        }

        // Direct repo listing
        const [owner, repo] = input.repo.split("/");
        const resp = await octokit.issues.listForRepo({
          owner,
          repo,
          state,
          labels: input.labels,
          per_page: maxResults,
        });

        // Filter out PRs (issues endpoint returns them too)
        const issues = resp.data.filter((i) => !i.pull_request);
        const header = `Issues (${state}) for ${input.repo}: ${issues.length} result(s)`;

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "list_issues", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return { content: [{ type: "text" as const, text: formatIssues(header, issues) }] };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "list_issues", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error listing issues: ${message}` }], isError: true };
      }
    },
  );
}

function formatIssues(header: string, issues: Array<Record<string, unknown>>): string {
  if (issues.length === 0) return `${header}\n\nNo issues found.`;
  const lines = [header, ""];
  issues.forEach((issue, i) => {
    const number = issue.number as number;
    const title = issue.title as string;
    const author = (issue.user as Record<string, unknown>)?.login ?? "unknown";
    const created = (issue.created_at as string)?.slice(0, 10) ?? "";
    const comments = issue.comments as number ?? 0;
    const labels = (issue.labels as Array<Record<string, unknown>>)?.map((l) => l.name).filter(Boolean) ?? [];
    const labelStr = labels.length > 0 ? ` [${labels.join(", ")}]` : "";
    const url = (issue.html_url as string) ?? "";

    lines.push(`${i + 1}. #${number} — ${title}${labelStr}`);
    lines.push(`   Author: ${author} | Created: ${created} | Comments: ${comments}`);
    if (url) lines.push(`   ${url}`);
    lines.push("");
  });
  return lines.join("\n").trimEnd();
}
