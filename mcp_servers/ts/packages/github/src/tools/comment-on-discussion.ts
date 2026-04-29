import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import type { graphql } from "@octokit/graphql";

export function registerCommentOnDiscussion(server: McpServer, logger: Logger, gql: typeof graphql): void {
  server.registerTool(
    "comment_on_discussion",
    {
      description: "Add a comment or reply to a GitHub discussion. Use discussion_id from get_discussion or list_discussions. For threaded replies, provide reply_to_id (a top-level comment ID).",
      inputSchema: {
        discussion_id: z.string().min(1).describe("Discussion node ID (from get_discussion or list_discussions)"),
        body: z.string().min(1).describe("Comment body (GitHub Flavored Markdown)"),
        reply_to_id: z.string().describe("Comment node ID to reply to (for threaded replies). Omit for top-level comment").optional(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "comment_on_discussion", request_id: requestId }, "tool_call_start");

      try {
        const result = await gql<{
          addDiscussionComment: {
            comment: {
              id: string;
              url: string;
              body: string;
              createdAt: string;
              author: { login: string } | null;
              isAnswer: boolean;
            };
          };
        }>(
          `mutation AddComment($discussionId: ID!, $body: String!, $replyToId: ID) {
            addDiscussionComment(input: {
              discussionId: $discussionId
              body: $body
              replyToId: $replyToId
            }) {
              comment {
                id url body createdAt isAnswer
                author { login }
              }
            }
          }`,
          {
            discussionId: input.discussion_id,
            body: input.body,
            replyToId: input.reply_to_id ?? null,
          },
        );

        const comment = result.addDiscussionComment.comment;
        const replyNote = input.reply_to_id ? " (reply)" : "";

        const structured = {
          success: true,
          id: comment.id,
          url: comment.url,
          author: comment.author?.login ?? "unknown",
          created_at: comment.createdAt,
          is_answer: comment.isAnswer,
        };

        const text = `Comment added${replyNote}: ${comment.url}`;

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "comment_on_discussion", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "comment_on_discussion", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error commenting on discussion: ${message}` }], isError: true };
      }
    },
  );
}
