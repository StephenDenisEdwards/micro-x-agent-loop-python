import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { graphql } from "@octokit/graphql";
import { getDiscussionCategories } from "../graphql/client.js";

export function registerGetDiscussionCategories(server: McpServer, logger: Logger, gql: typeof graphql): void {
  server.registerTool(
    "get_discussion_categories",
    {
      description: "List available discussion categories for a GitHub repository. Use this to discover valid categories before creating a discussion.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "get_discussion_categories", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");
        const categories = await getDiscussionCategories(gql, owner, repo);

        if (categories.length === 0) {
          return {
            content: [{ type: "text" as const, text: `Discussions are not enabled for ${input.repo}. Enable them in Settings > Features > Discussions.` }],
          };
        }

        const structured = {
          repo: input.repo,
          categories: categories.map((c) => ({
            name: c.name,
            emoji: c.emoji,
            description: c.description,
            is_answerable: c.isAnswerable,
          })),
        };

        const lines = [`Discussion categories for ${input.repo}: ${categories.length} found`, ""];
        for (const c of categories) {
          const answerable = c.isAnswerable ? " [Q&A]" : "";
          lines.push(`${c.emoji} ${c.name}${answerable}`);
          if (c.description) lines.push(`  ${c.description}`);
          lines.push("");
        }

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "get_discussion_categories", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: lines.join("\n").trimEnd() }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "get_discussion_categories", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error listing discussion categories: ${message}` }], isError: true };
      }
    },
  );
}
