import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";

const DEVTO_API = "https://dev.to/api";

export function registerPublishArticle(
  server: McpServer,
  logger: Logger,
  apiKey: string,
): void {
  server.registerTool(
    "devto_publish_article",
    {
      description:
        "Publish an existing Dev.to draft article by setting its published status to true.",
      inputSchema: {
        article_id: z.number().int().describe("Article ID to publish"),
      },
      outputSchema: {
        article_id: z.number().int(),
        title: z.string(),
        url: z.string(),
        published: z.boolean(),
        published_at: z.string().nullable(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "devto_publish_article", request_id: requestId, article_id: input.article_id }, "tool_call_start");

      try {
        const response = await resilientFetch(
          `${DEVTO_API}/articles/${input.article_id}`,
          {
            method: "PUT",
            headers: {
              "api-key": apiKey,
              "Accept": "application/vnd.forem.api-v1+json",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ article: { published: true } }),
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

        const data = await response.json() as {
          id: number;
          title: string;
          url: string;
          published: boolean;
          published_at: string | null;
        };

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "devto_publish_article", request_id: requestId, duration_ms: durationMs, outcome: "success", article_id: data.id },
          "tool_call_end",
        );

        const result = {
          article_id: data.id,
          title: data.title,
          url: data.url,
          published: data.published,
          published_at: data.published_at,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: [
              `Article published successfully!`,
              ``,
              `Article ID: ${data.id}`,
              `Title: ${data.title}`,
              `URL: ${data.url}`,
              `Published at: ${data.published_at ?? "N/A"}`,
            ].join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "devto_publish_article", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error publishing article: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
