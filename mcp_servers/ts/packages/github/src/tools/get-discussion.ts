import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { graphql } from "@octokit/graphql";

interface CommentReply {
  id: string;
  body: string;
  author: { login: string } | null;
  createdAt: string;
}

interface Comment {
  id: string;
  body: string;
  createdAt: string;
  isAnswer: boolean;
  author: { login: string } | null;
  replies: { totalCount: number; nodes: CommentReply[] };
}

interface Discussion {
  id: string;
  number: number;
  title: string;
  body: string;
  createdAt: string;
  updatedAt: string;
  url: string;
  isAnswered: boolean;
  answer: { id: string; body: string; author: { login: string } | null; createdAt: string } | null;
  category: { name: string; isAnswerable: boolean };
  author: { login: string } | null;
  labels: { nodes: Array<{ name: string; color: string }> };
  comments: { totalCount: number; nodes: Comment[] };
}

export function registerGetDiscussion(server: McpServer, logger: Logger, gql: typeof graphql): void {
  server.registerTool(
    "get_discussion",
    {
      description: "Get a GitHub discussion with its comments by number.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        number: z.number().int().min(1).describe("Discussion number"),
        comment_limit: z.number().int().min(1).max(100).default(20).describe("Max comments to return (default 20, max 100)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const commentLimit = input.comment_limit ?? 20;

      logger.info({ tool: "get_discussion", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");

        const result = await gql<{ repository: { discussion: Discussion | null } }>(
          `query GetDiscussion($owner: String!, $name: String!, $number: Int!, $commentLimit: Int!) {
            repository(owner: $owner, name: $name) {
              discussion(number: $number) {
                id number title body createdAt updatedAt url isAnswered
                answer {
                  id body createdAt
                  author { login }
                }
                category { name isAnswerable }
                author { login }
                labels(first: 10) { nodes { name color } }
                comments(first: $commentLimit) {
                  totalCount
                  nodes {
                    id body createdAt isAnswer
                    author { login }
                    replies(first: 5) {
                      totalCount
                      nodes {
                        id body createdAt
                        author { login }
                      }
                    }
                  }
                }
              }
            }
          }`,
          { owner, name: repo, number: input.number, commentLimit },
        );

        const d = result.repository.discussion;
        if (!d) {
          return {
            content: [{ type: "text" as const, text: `Discussion #${input.number} not found in ${input.repo}.` }],
            isError: true,
          };
        }

        const structured = {
          id: d.id,
          number: d.number,
          title: d.title,
          body: d.body,
          url: d.url,
          category: d.category.name,
          is_answerable: d.category.isAnswerable,
          is_answered: d.isAnswered,
          author: d.author?.login ?? "unknown",
          created_at: d.createdAt,
          updated_at: d.updatedAt,
          labels: d.labels.nodes.map((l) => l.name),
          comment_count: d.comments.totalCount,
          answer: d.answer
            ? { id: d.answer.id, author: d.answer.author?.login ?? "unknown", body: d.answer.body, created_at: d.answer.createdAt }
            : null,
          comments: d.comments.nodes.map((c) => ({
            id: c.id,
            author: c.author?.login ?? "unknown",
            body: c.body,
            created_at: c.createdAt,
            is_answer: c.isAnswer,
            reply_count: c.replies.totalCount,
            replies: c.replies.nodes.map((r) => ({
              id: r.id,
              author: r.author?.login ?? "unknown",
              body: r.body,
              created_at: r.createdAt,
            })),
          })),
        };

        const lines = [
          `#${d.number} — ${d.title}`,
          `Category: ${d.category.name} | Author: ${d.author?.login ?? "unknown"} | Created: ${d.createdAt.slice(0, 10)}`,
        ];
        if (d.labels.nodes.length > 0) {
          lines.push(`Labels: ${d.labels.nodes.map((l) => l.name).join(", ")}`);
        }
        if (d.isAnswered && d.answer) {
          lines.push(`Answered by: ${d.answer.author?.login ?? "unknown"}`);
        }
        lines.push(`URL: ${d.url}`, "", "---", "", d.body);

        if (d.comments.nodes.length > 0) {
          lines.push("", `--- Comments (${d.comments.nodes.length} of ${d.comments.totalCount}) ---`, "");
          for (const c of d.comments.nodes) {
            const answerTag = c.isAnswer ? " [ANSWER]" : "";
            lines.push(`${c.author?.login ?? "unknown"}${answerTag} (${c.createdAt.slice(0, 10)}):`);
            lines.push(c.body);
            for (const r of c.replies.nodes) {
              lines.push(`  └ ${r.author?.login ?? "unknown"} (${r.createdAt.slice(0, 10)}):`);
              lines.push(`    ${r.body}`);
            }
            if (c.replies.totalCount > c.replies.nodes.length) {
              lines.push(`  ... and ${c.replies.totalCount - c.replies.nodes.length} more replies`);
            }
            lines.push("");
          }
        }

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "get_discussion", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: lines.join("\n").trimEnd() }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "get_discussion", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error getting discussion: ${message}` }], isError: true };
      }
    },
  );
}
