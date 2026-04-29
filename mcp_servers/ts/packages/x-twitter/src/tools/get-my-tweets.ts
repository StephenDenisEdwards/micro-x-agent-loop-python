import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";
import { getXClient } from "../auth/x-auth.js";

export function registerGetMyTweets(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "x_get_my_tweets",
    {
      description:
        "Get the authenticated user's recent tweets with metrics. " +
        "Note: On the free tier, reads are severely limited (~100/month). " +
        "This tool may return a quota error.",
      inputSchema: {
        max_results: z
          .number()
          .int()
          .min(5)
          .max(100)
          .default(10)
          .optional()
          .describe("Number of tweets to return (default 10, max 100)"),
      },
      outputSchema: {
        tweets: z.array(z.object({
          tweet_id: z.string(),
          text: z.string(),
          created_at: z.string(),
          public_metrics: z.object({
            retweet_count: z.number().int(),
            reply_count: z.number().int(),
            like_count: z.number().int(),
            quote_count: z.number().int(),
            impression_count: z.number().int(),
          }),
          url: z.string(),
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

      logger.info({ tool: "x_get_my_tweets", request_id: requestId }, "tool_call_start");

      try {
        const client = await getXClient(clientId, clientSecret);
        const maxResults = input.max_results ?? 10;

        const params = new URLSearchParams({
          "tweet.fields": "created_at,public_metrics,conversation_id",
          "max_results": maxResults.toString(),
        });

        const response = await resilientFetch(
          `https://api.x.com/2/users/${client.userId}/tweets?${params.toString()}`,
          {
            headers: {
              "Authorization": `Bearer ${client.accessToken}`,
            },
          },
          { timeoutMs: 15_000, retries: 2 },
        );

        if (response.status === 429) {
          const durationMs = Date.now() - startTime;
          logger.warn(
            { tool: "x_get_my_tweets", request_id: requestId, duration_ms: durationMs, outcome: "rate_limited" },
            "tool_call_end",
          );
          return {
            content: [{
              type: "text" as const,
              text: "X API read quota exhausted. On the free tier, reads are limited to ~100/month. Upgrade to Basic or pay-per-use for more read access.",
            }],
            isError: true,
          };
        }

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `X API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        const data = await response.json() as {
          data?: Array<{
            id: string;
            text: string;
            created_at: string;
            public_metrics: {
              retweet_count: number;
              reply_count: number;
              like_count: number;
              quote_count: number;
              impression_count: number;
            };
          }>;
          meta: { result_count: number };
        };

        const tweets = (data.data ?? []).map(t => ({
          tweet_id: t.id,
          text: t.text,
          created_at: t.created_at,
          public_metrics: t.public_metrics,
          url: `https://x.com/${client.username}/status/${t.id}`,
        }));

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_get_my_tweets", request_id: requestId, duration_ms: durationMs, outcome: "success", result_count: tweets.length },
          "tool_call_end",
        );

        const result = {
          tweets,
          result_count: tweets.length,
        };

        const lines = tweets.map((t, i) => {
          const m = t.public_metrics;
          const preview = t.text.length > 80 ? t.text.substring(0, 80) + "..." : t.text;
          return `${i + 1}. ${preview}\n   ${t.created_at} | Likes: ${m.like_count} | RT: ${m.retweet_count} | Impressions: ${m.impression_count}`;
        });

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: tweets.length > 0
              ? `Recent tweets by @${client.username} (${tweets.length}):\n\n${lines.join("\n\n")}`
              : "No recent tweets found.",
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_get_my_tweets", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching tweets: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
