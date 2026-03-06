import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";

const DEVTO_API = "https://dev.to/api";

export function registerCreateArticle(
  server: McpServer,
  logger: Logger,
  apiKey: string,
): void {
  server.registerTool(
    "devto_create_article",
    {
      description:
        "Create a new Dev.to article as a draft (unpublished). " +
        "Returns the article ID which can be used with devto_publish_article to publish.",
      inputSchema: {
        title: z.string().min(1).describe("Article title"),
        body_markdown: z.string().min(1).describe("Article body in Markdown"),
        tags: z
          .array(z.string())
          .max(4)
          .optional()
          .describe("Tags (max 4)"),
        series: z.string().optional().describe("Series name to group articles"),
        canonical_url: z.string().url().optional().describe("Canonical URL if cross-posting"),
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
        idempotentHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "devto_create_article", request_id: requestId }, "tool_call_start");

      try {
        const article: Record<string, unknown> = {
          title: input.title,
          body_markdown: input.body_markdown,
          published: false,
        };

        if (input.tags?.length) article.tags = input.tags;
        if (input.series) article.series = input.series;
        if (input.canonical_url) article.canonical_url = input.canonical_url;
        if (input.cover_image_url) article.main_image = input.cover_image_url;
        if (input.description) article.description = input.description;

        const response = await resilientFetch(
          `${DEVTO_API}/articles`,
          {
            method: "POST",
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
          { tool: "devto_create_article", request_id: requestId, duration_ms: durationMs, outcome: "success", article_id: data.id },
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
              `Draft article created successfully.`,
              ``,
              `Article ID: ${data.id}`,
              `Title: ${data.title}`,
              `URL: ${data.url}`,
              `Published: ${data.published}`,
              `Tags: ${data.tag_list.join(", ") || "(none)"}`,
              ``,
              `Use devto_publish_article with article_id ${data.id} to publish.`,
            ].join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "devto_create_article", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating article: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
