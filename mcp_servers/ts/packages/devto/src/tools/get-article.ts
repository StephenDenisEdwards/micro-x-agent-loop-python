import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";

const DEVTO_API = "https://dev.to/api";

export function registerGetArticle(
  server: McpServer,
  logger: Logger,
  apiKey: string,
): void {
  server.registerTool(
    "devto_get_article",
    {
      description:
        "Get full details of a Dev.to article including body content and metrics.",
      inputSchema: {
        article_id: z.number().int().describe("Article ID"),
      },
      outputSchema: {
        article_id: z.number().int(),
        title: z.string(),
        url: z.string(),
        slug: z.string(),
        published: z.boolean(),
        published_at: z.string().nullable(),
        tags: z.array(z.string()),
        body_markdown: z.string(),
        description: z.string(),
        cover_image: z.string().nullable(),
        positive_reactions_count: z.number().int(),
        comments_count: z.number().int(),
        page_views_count: z.number().int(),
        reading_time_minutes: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "devto_get_article", request_id: requestId, article_id: input.article_id }, "tool_call_start");

      try {
        const response = await resilientFetch(
          `${DEVTO_API}/articles/${input.article_id}`,
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

        const data = await response.json() as {
          id: number;
          title: string;
          url: string;
          slug: string;
          published: boolean;
          published_at: string | null;
          tag_list: string[];
          body_markdown: string;
          description: string;
          cover_image: string | null;
          positive_reactions_count: number;
          comments_count: number;
          page_views_count: number;
          reading_time_minutes: number;
        };

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "devto_get_article", request_id: requestId, duration_ms: durationMs, outcome: "success", article_id: data.id },
          "tool_call_end",
        );

        const result = {
          article_id: data.id,
          title: data.title,
          url: data.url,
          slug: data.slug,
          published: data.published,
          published_at: data.published_at,
          tags: data.tag_list,
          body_markdown: data.body_markdown,
          description: data.description,
          cover_image: data.cover_image,
          positive_reactions_count: data.positive_reactions_count,
          comments_count: data.comments_count,
          page_views_count: data.page_views_count,
          reading_time_minutes: data.reading_time_minutes,
        };

        const bodyPreview = data.body_markdown.length > 300
          ? data.body_markdown.substring(0, 300) + "..."
          : data.body_markdown;

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: [
              `Article ${data.id}: ${data.title}`,
              `Status: ${data.published ? "published" : "draft"}`,
              `URL: ${data.url}`,
              `Published at: ${data.published_at ?? "N/A"}`,
              `Tags: ${data.tag_list.join(", ") || "(none)"}`,
              `Reading time: ${data.reading_time_minutes} min`,
              `Views: ${data.page_views_count} | Reactions: ${data.positive_reactions_count} | Comments: ${data.comments_count}`,
              ``,
              `Description: ${data.description}`,
              ``,
              `Body preview:`,
              bodyPreview,
            ].join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "devto_get_article", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching article: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
