import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerCreatePR(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "create_pr",
    {
      description: "Create a pull request in a GitHub repository.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        title: z.string().min(1).describe("PR title"),
        head: z.string().min(1).describe("Branch containing changes"),
        body: z.string().describe("PR description (markdown)").optional(),
        base: z.string().default("main").describe("Branch to merge into (default: main)").optional(),
        draft: z.boolean().default(false).describe("Create as draft PR (default: false)").optional(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "create_pr", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");
        const resp = await octokit.pulls.create({
          owner,
          repo,
          title: input.title,
          head: input.head,
          base: input.base ?? "main",
          body: input.body,
          draft: input.draft ?? false,
        });

        const pr = resp.data;
        const draft = pr.draft ? " (draft)" : "";
        const text = `PR created: #${pr.number} — ${pr.title}${draft}\nBranch: ${pr.head.ref} -> ${pr.base.ref}\n${pr.html_url}`;

        const structured = {
          number: pr.number,
          title: pr.title,
          draft: pr.draft ?? false,
          head: pr.head.ref,
          base: pr.base.ref,
          url: pr.html_url,
        };

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "create_pr", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "create_pr", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error creating PR: ${message}` }], isError: true };
      }
    },
  );
}
