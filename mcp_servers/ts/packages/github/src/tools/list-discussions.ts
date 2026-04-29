import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import type { graphql } from "@octokit/graphql";
import { resolveCategoryId } from "../graphql/client.js";

interface DiscussionNode {
  id: string;
  number: number;
  title: string;
  createdAt: string;
  updatedAt: string;
  url: string;
  isAnswered: boolean;
  category: { name: string };
  author: { login: string } | null;
  comments: { totalCount: number };
  labels: { nodes: Array<{ name: string }> };
}

export function registerListDiscussions(server: McpServer, logger: Logger, gql: typeof graphql): void {
  server.registerTool(
    "list_discussions",
    {
      description: "List discussions in a GitHub repository with optional filters.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        category: z.string().describe("Filter by category name").optional(),
        answered: z.boolean().describe("Filter Q&A discussions: true = answered only, false = unanswered only").optional(),
        sort: z.enum(["CREATED_AT", "UPDATED_AT"]).default("CREATED_AT").describe("Sort field (default: CREATED_AT)").optional(),
        direction: z.enum(["DESC", "ASC"]).default("DESC").describe("Sort direction (default: DESC)").optional(),
        max_results: z.number().int().min(1).max(100).default(10).describe("Number of results (default 10, max 100)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const maxResults = input.max_results ?? 10;
      const sort = input.sort ?? "CREATED_AT";
      const direction = input.direction ?? "DESC";

      logger.info({ tool: "list_discussions", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");

        // Resolve category ID if filtering by category
        let categoryId: string | undefined;
        if (input.category) {
          const resolved = await resolveCategoryId(gql, owner, repo, input.category);
          if (!resolved) {
            return {
              content: [{ type: "text" as const, text: `Category "${input.category}" not found in ${input.repo}.` }],
              isError: true,
            };
          }
          categoryId = resolved.id;
        }

        const result = await gql<{
          repository: {
            discussions: {
              totalCount: number;
              nodes: DiscussionNode[];
            };
          };
        }>(
          `query ListDiscussions($owner: String!, $name: String!, $first: Int!, $categoryId: ID, $answered: Boolean, $orderBy: DiscussionOrder) {
            repository(owner: $owner, name: $name) {
              discussions(first: $first, categoryId: $categoryId, answered: $answered, orderBy: $orderBy) {
                totalCount
                nodes {
                  id number title createdAt updatedAt url isAnswered
                  category { name }
                  author { login }
                  comments { totalCount }
                  labels(first: 5) { nodes { name } }
                }
              }
            }
          }`,
          {
            owner,
            name: repo,
            first: maxResults,
            categoryId: categoryId ?? null,
            answered: input.answered ?? null,
            orderBy: { field: sort, direction },
          },
        );

        const { totalCount, nodes } = result.repository.discussions;

        const structured = {
          total_count: totalCount,
          discussions: nodes.map((d) => ({
            id: d.id,
            number: d.number,
            title: d.title,
            url: d.url,
            category: d.category.name,
            author: d.author?.login ?? "unknown",
            created_at: d.createdAt,
            updated_at: d.updatedAt,
            is_answered: d.isAnswered,
            comment_count: d.comments.totalCount,
            labels: d.labels.nodes.map((l) => l.name),
          })),
        };

        const filterDesc = input.category ? ` in ${input.category}` : "";
        const lines = [`Discussions for ${input.repo}${filterDesc}: ${nodes.length} of ${totalCount} total`, ""];

        if (nodes.length === 0) {
          lines.push("No discussions found.");
        } else {
          for (const d of nodes) {
            const labels = d.labels.nodes.length > 0 ? ` [${d.labels.nodes.map((l) => l.name).join(", ")}]` : "";
            const answered = d.isAnswered ? " (answered)" : "";
            lines.push(`${d.number}. ${d.title}${labels}${answered}`);
            lines.push(`   Category: ${d.category.name} | Author: ${d.author?.login ?? "unknown"} | Comments: ${d.comments.totalCount}`);
            lines.push(`   Created: ${d.createdAt.slice(0, 10)} | ${d.url}`);
            lines.push("");
          }
        }

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "list_discussions", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: lines.join("\n").trimEnd() }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "list_discussions", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error listing discussions: ${message}` }], isError: true };
      }
    },
  );
}
