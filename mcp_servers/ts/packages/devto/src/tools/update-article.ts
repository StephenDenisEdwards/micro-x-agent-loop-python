import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";

const DEVTO_API = "https://dev.to/api";

export function registerUpdateArticle(
  server: McpServer,
  logger: Logger,
  apiKey: string,
): void {
  server.registerTool(
    "devto_update_article",
    {
      description:
        "Update an existing Dev.to article's content or metadata. " +
        "Does NOT change the published status — use devto_publish_article for that.",
      inputSchema: {
        article_id: z.number().int().describe("Article ID to update"),
        title: z.string().min(1).optional().describe("New title"),
        body_markdown: z.string().min(1).optional().describe("New body in Markdown"),
        tags: z
          .array(z.string())
          .max(4)
          .optional()
          .describe("New tags (max 4)"),
        series: z.string().optional().describe("Series name"),
        canonical_url: z.string().url().optional().describe("Canonical URL"),
        cover_image_url: z.string().url().optional().describe("Cover image URL (maps to main_image in API)"),
        description: z.string().max(256).optional().describe("Short description for SEO (max 256 chars)"),
      },
      outputSchema: {
        article_id: z.number().int(),
        title: z.string(),
        url: z.string(),
        slug: z.string(),
        published: z.boolean(),
        tags: z.array(z.string()),
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

      logger.info({ tool: "devto_update_article", request_id: requestId, article_id: input.article_id }, "tool_call_start");

      try {
        const article: Record<string, unknown> = {};

        if (input.title !== undefined) article.title = input.title;
        if (input.body_markdown !== undefined) article.body_markdown = input.body_markdown;
        if (input.tags !== undefined) article.tags = input.tags;
        if (input.series !== undefined) article.series = input.series;
        if (input.canonical_url !== undefined) article.canonical_url = input.canonical_url;
        if (input.cover_image_url !== undefined) article.main_image = input.cover_image_url;
        if (input.description !== undefined) article.description = input.description;

        if (Object.keys(article).length === 0) {
          const durationMs = Date.now() - startTime;
          logger.warn(
            { tool: "devto_update_article", request_id: requestId, duration_ms: durationMs, outcome: "no_fields" },
            "tool_call_end",
          );
          return {
            content: [{ type: "text" as const, text: "No fields provided to update. Specify at least one field to change." }],
            isError: true,
          };
        }

        const response = await resilientFetch(
          `${DEVTO_API}/articles/${input.article_id}`,
          {
            method: "PUT",
            headers: {
              "api-key": apiKey,
              "Accept": "application/vnd.forem.api-v1+json",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ article }),
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
          slug: string;
          published: boolean;
          tag_list: string[];
        };

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "devto_update_article", request_id: requestId, duration_ms: durationMs, outcome: "success", article_id: data.id },
          "tool_call_end",
        );

        const result = {
          article_id: data.id,
          title: data.title,
          url: data.url,
          slug: data.slug,
          published: data.published,
          tags: data.tag_list,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: [
              `Article updated successfully.`,
              ``,
              `Article ID: ${data.id}`,
              `Title: ${data.title}`,
              `URL: ${data.url}`,
              `Published: ${data.published}`,
              `Tags: ${data.tag_list.join(", ") || "(none)"}`,
            ].join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "devto_update_article", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error updating article: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
