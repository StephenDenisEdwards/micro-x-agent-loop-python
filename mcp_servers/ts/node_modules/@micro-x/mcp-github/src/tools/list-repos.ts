import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { Octokit } from "@octokit/rest";

export function registerListRepos(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "list_repos",
    {
      description:
        "List GitHub repositories for the authenticated user or a specific owner. If owner is omitted, lists your own repositories.",
      inputSchema: {
        owner: z.string().describe("Username or organization. If omitted, lists your repos.").optional(),
        type: z
          .enum(["all", "owner", "public", "private", "member"])
          .default("all")
          .describe("Filter by type (default: all)")
          .optional(),
        sort: z
          .enum(["created", "updated", "pushed", "full_name"])
          .default("updated")
          .describe("Sort field (default: updated)")
          .optional(),
        maxResults: z.number().int().min(1).max(30).default(10).describe("Max results (default 10, max 30)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const maxResults = input.maxResults ?? 10;
      const sort = input.sort ?? "updated";
      const repoType = input.type ?? "all";

      logger.info({ tool: "list_repos", request_id: requestId }, "tool_call_start");

      try {
        let repos: Array<Record<string, unknown>>;

        if (input.owner) {
          const resp = await octokit.repos.listForUser({
            username: input.owner,
            type: repoType as "all" | "owner" | "member",
            sort: sort as "created" | "updated" | "pushed" | "full_name",
            direction: "desc",
            per_page: maxResults,
          });
          repos = resp.data as unknown as Array<Record<string, unknown>>;
        } else {
          const resp = await octokit.repos.listForAuthenticatedUser({
            type: repoType as "all" | "owner" | "private" | "public" | "member",
            sort: sort as "created" | "updated" | "pushed" | "full_name",
            direction: "desc",
            per_page: maxResults,
          });
          repos = resp.data as unknown as Array<Record<string, unknown>>;
        }

        const who = input.owner || "you";
        const header = `Repos for ${who}: ${repos.length} result(s)`;

        if (repos.length === 0) {
          return { content: [{ type: "text" as const, text: `${header}\n\nNo repositories found.` }] };
        }

        const lines = [header, ""];
        repos.forEach((repo, i) => {
          const name = (repo.full_name as string) ?? "?";
          let desc = (repo.description as string) ?? "";
          if (desc.length > 100) desc = desc.slice(0, 100) + "...";
          const visibility = repo.private ? "private" : "public";
          const language = (repo.language as string) ?? "";
          const stars = (repo.stargazers_count as number) ?? 0;
          const updated = ((repo.updated_at as string) ?? "").slice(0, 10);

          lines.push(`${i + 1}. ${name} [${visibility}]`);
          if (desc) lines.push(`   ${desc}`);
          const detail = [language, `stars: ${stars}`, `updated: ${updated}`].filter(Boolean).join(" | ");
          lines.push(`   ${detail}`);
          lines.push("");
        });

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "list_repos", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return { content: [{ type: "text" as const, text: lines.join("\n").trimEnd() }] };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "list_repos", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error listing repos: ${message}` }], isError: true };
      }
    },
  );
}
