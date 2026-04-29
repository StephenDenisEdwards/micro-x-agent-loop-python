import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";

const DEVTO_API = "https://dev.to/api";

export function registerGetArticleComments(
  server: McpServer,
  logger: Logger,
  apiKey: string,
): void {
  server.registerTool(
    "devto_get_article_comments",
    {
      description:
        "Get comments on a Dev.to article.",
      inputSchema: {
        article_id: z.number().int().describe("Article ID to get comments for"),
      },
      outputSchema: {
        comments: z.array(z.object({
          comment_id: z.string(),
          body_html: z.string(),
          user: z.object({
            username: z.string(),
            name: z.string(),
          }),
          created_at: z.string(),
          children: z.array(z.unknown()),
        })),
        result_count: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "devto_get_article_comments", request_id: requestId, article_id: input.article_id }, "tool_call_start");

      try {
        const params = new URLSearchParams({
          a_id: input.article_id.toString(),
        });

        const response = await resilientFetch(
          `${DEVTO_API}/comments?${params.toString()}`,
          {
            headers: {
              "api-key": apiKey,
              "Accept": "application/vnd.forem.api-v1+json",
            },
          },
          { timeoutMs: 30_000, retries: 2 },
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `Dev.to API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        const data = await response.json() as Array<{
          id_code: string;
          body_html: string;
          user: {
            username: string;
            name: string;
          };
          created_at: string;
          children: unknown[];
        }>;

        const comments = data.map(c => ({
          comment_id: c.id_code,
          body_html: c.body_html,
          user: {
            username: c.user.username,
            name: c.user.name,
          },
          created_at: c.created_at,
          children: c.children,
        }));

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "devto_get_article_comments", request_id: requestId, duration_ms: durationMs, outcome: "success", result_count: comments.length },
          "tool_call_end",
        );

        const result = {
          comments,
          result_count: comments.length,
        };

        const lines = comments.map((c, i) => {
          // Strip HTML tags for text preview
          const textPreview = c.body_html.replace(/<[^>]*>/g, "").substring(0, 100);
          return `${i + 1}. @${c.user.username} (${c.created_at}):\n   ${textPreview}${c.body_html.length > 100 ? "..." : ""}`;
        });

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: comments.length > 0
              ? `Comments on article ${input.article_id} (${comments.length}):\n\n${lines.join("\n\n")}`
              : `No comments found on article ${input.article_id}.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "devto_get_article_comments", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching comments: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
