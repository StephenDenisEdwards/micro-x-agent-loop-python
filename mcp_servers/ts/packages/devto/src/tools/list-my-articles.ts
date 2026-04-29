import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";

const DEVTO_API = "https://dev.to/api";

const STATUS_ENDPOINTS: Record<string, string> = {
  all: "/articles/me/all",
  published: "/articles/me/published",
  draft: "/articles/me/unpublished",
};

export function registerListMyArticles(
  server: McpServer,
  logger: Logger,
  apiKey: string,
): void {
  server.registerTool(
    "devto_list_my_articles",
    {
      description:
        "List your Dev.to articles. Filter by status (all, published, or draft).",
      inputSchema: {
        status: z
          .enum(["all", "published", "draft"])
          .default("all")
          .optional()
          .describe("Filter by status (default: all)"),
        page: z
          .number()
          .int()
          .min(1)
          .default(1)
          .optional()
          .describe("Page number (default: 1)"),
        per_page: z
          .number()
          .int()
          .min(1)
          .max(1000)
          .default(30)
          .optional()
          .describe("Articles per page (default: 30, max: 1000)"),
      },
      outputSchema: {
        articles: z.array(z.object({
          article_id: z.number().int(),
          title: z.string(),
          url: z.string(),
          published: z.boolean(),
          published_at: z.string().nullable(),
          tags: z.array(z.string()),
          positive_reactions_count: z.number().int(),
          comments_count: z.number().int(),
          page_views_count: z.number().int(),
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

      logger.info({ tool: "devto_list_my_articles", request_id: requestId }, "tool_call_start");

      try {
        const status = input.status ?? "all";
        const page = input.page ?? 1;
        const perPage = input.per_page ?? 30;

        const endpoint = STATUS_ENDPOINTS[status];
        const params = new URLSearchParams({
          page: page.toString(),
          per_page: perPage.toString(),
        });

        const response = await resilientFetch(
          `${DEVTO_API}${endpoint}?${params.toString()}`,
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
          id: number;
          title: string;
          url: string;
          published: boolean;
          published_at: string | null;
          tag_list: string[];
          positive_reactions_count: number;
          comments_count: number;
          page_views_count: number;
        }>;

        const articles = data.map(a => ({
          article_id: a.id,
          title: a.title,
          url: a.url,
          published: a.published,
          published_at: a.published_at,
          tags: a.tag_list,
          positive_reactions_count: a.positive_reactions_count,
          comments_count: a.comments_count,
          page_views_count: a.page_views_count,
        }));

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "devto_list_my_articles", request_id: requestId, duration_ms: durationMs, outcome: "success", result_count: articles.length },
          "tool_call_end",
        );

        const result = {
          articles,
          result_count: articles.length,
        };

        const lines = articles.map((a, i) => {
          const statusLabel = a.published ? "published" : "draft";
          return `${i + 1}. [${statusLabel}] ${a.title}\n   ID: ${a.article_id} | Views: ${a.page_views_count} | Reactions: ${a.positive_reactions_count} | Comments: ${a.comments_count}`;
        });

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: articles.length > 0
              ? `Your Dev.to articles (${articles.length}, status: ${status}, page ${page}):\n\n${lines.join("\n\n")}`
              : `No articles found (status: ${status}, page ${page}).`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "devto_list_my_articles", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error listing articles: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
