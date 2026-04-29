import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerGetPR(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "get_pr",
    {
      description: "Get detailed information about a specific pull request, including diff stats, reviews, and CI status.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        number: z.number().int().min(1).describe("Pull request number"),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "get_pr", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");
        const pull_number = input.number;

        const [prResp, reviewsResp] = await Promise.all([
          octokit.pulls.get({ owner, repo, pull_number }),
          octokit.pulls.listReviews({ owner, repo, pull_number }),
        ]);

        const pr = prResp.data;
        const reviews = reviewsResp.data;

        let ciStatus = "no checks";
        try {
          const checksResp = await octokit.checks.listForRef({ owner, repo, ref: pr.head.sha });
          const runs = checksResp.data.check_runs;
          if (runs.length > 0) {
            const conclusions = runs.map((r) => r.conclusion);
            if (conclusions.every((c) => c === "success")) ciStatus = "passing";
            else if (conclusions.some((c) => c === "failure")) ciStatus = "failing";
            else if (conclusions.some((c) => c === null)) ciStatus = "in progress";
            else ciStatus = [...new Set(conclusions)].join(", ");
          }
        } catch { /* ignore check failures */ }

        const approved = reviews.filter((r) => r.state === "APPROVED").length;
        const changesRequested = reviews.filter((r) => r.state === "CHANGES_REQUESTED").length;
        const draft = pr.draft ? " (draft)" : "";
        const mergeable = pr.mergeable === true ? "yes" : pr.mergeable === false ? "no" : "unknown";

        const body = pr.body && pr.body.length > 1000 ? pr.body.slice(0, 1000) + "..." : (pr.body || "");

        const lines = [
          `#${pr.number} — ${pr.title}${draft}`,
          `State: ${pr.state} | Mergeable: ${mergeable}`,
          `Author: ${pr.user?.login ?? "unknown"} | Branch: ${pr.head.ref} -> ${pr.base.ref}`,
          `Created: ${pr.created_at.slice(0, 10)} | Updated: ${pr.updated_at.slice(0, 10)}`,
          `Reviews: ${approved} approved, ${changesRequested} changes requested`,
          `CI: ${ciStatus}`,
          `Diff: +${pr.additions} -${pr.deletions} in ${pr.changed_files} file(s)`,
          `URL: ${pr.html_url}`,
        ];
        if (body) { lines.push(""); lines.push(body); }

        const structured = {
          number: pr.number,
          title: pr.title,
          state: pr.state,
          draft: pr.draft ?? false,
          mergeable,
          author: pr.user?.login ?? "unknown",
          head: pr.head.ref,
          base: pr.base.ref,
          created: pr.created_at.slice(0, 10),
          updated: pr.updated_at.slice(0, 10),
          approved_reviews: approved,
          changes_requested: changesRequested,
          ci_status: ciStatus,
          additions: pr.additions,
          deletions: pr.deletions,
          changed_files: pr.changed_files,
          url: pr.html_url,
          body,
        };

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "get_pr", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: lines.join("\n") }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "get_pr", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error getting PR: ${message}` }], isError: true };
      }
    },
  );
}
