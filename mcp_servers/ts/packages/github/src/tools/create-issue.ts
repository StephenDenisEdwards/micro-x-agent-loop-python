import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerCreateIssue(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "create_issue",
    {
      description: "Create a new issue in a GitHub repository.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        title: z.string().min(1).describe("Issue title"),
        body: z.string().describe("Issue body (markdown)").optional(),
        labels: z.array(z.string()).describe("Label names to apply").optional(),
        assignees: z.array(z.string()).describe("Usernames to assign").optional(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "create_issue", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");
        const resp = await octokit.issues.create({
          owner,
          repo,
          title: input.title,
          body: input.body,
          labels: input.labels,
          assignees: input.assignees,
        });

        const issue = resp.data;
        const text = `Issue created: #${issue.number} — ${issue.title}\n${issue.html_url}`;

        const structured = {
          number: issue.number,
          title: issue.title,
          url: issue.html_url,
          labels: (issue.labels as Array<Record<string, unknown>>)?.map((l) => l.name).filter(Boolean) ?? [],
        };

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "create_issue", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "create_issue", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error creating issue: ${message}` }], isError: true };
      }
    },
  );
}
