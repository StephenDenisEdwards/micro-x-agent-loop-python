import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";
import { getXClient } from "../auth/x-auth.js";

export function registerGetTweet(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "x_get_tweet",
    {
      description:
        "Get a tweet's details and public metrics. " +
        "Note: On the free tier, reads are severely limited (~100/month). " +
        "This tool may return a quota error.",
      inputSchema: {
        tweet_id: z.string().min(1).describe("Tweet ID"),
      },
      outputSchema: {
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
        conversation_id: z.string(),
        url: z.string(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "x_get_tweet", request_id: requestId, tweet_id: input.tweet_id }, "tool_call_start");

      try {
        const client = await getXClient(clientId, clientSecret);

        const params = new URLSearchParams({
          "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities",
          "expansions": "author_id",
        });

        const response = await resilientFetch(
          `https://api.x.com/2/tweets/${input.tweet_id}?${params.toString()}`,
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
            { tool: "x_get_tweet", request_id: requestId, duration_ms: durationMs, outcome: "rate_limited" },
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
          data: {
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
            conversation_id: string;
            author_id: string;
          };
          includes?: {
            users?: Array<{ id: string; username: string }>;
          };
        };

        const tweet = data.data;
        const author = data.includes?.users?.find(u => u.id === tweet.author_id);
        const username = author?.username ?? client.username;
        const url = `https://x.com/${username}/status/${tweet.id}`;

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_get_tweet", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        const result = {
          tweet_id: tweet.id,
          text: tweet.text,
          created_at: tweet.created_at,
          public_metrics: tweet.public_metrics,
          conversation_id: tweet.conversation_id,
          url,
        };

        const metrics = tweet.public_metrics;
        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: [
              `Tweet ${tweet.id} by @${username}`,
              `Created: ${tweet.created_at}`,
              "",
              tweet.text,
              "",
              `Impressions: ${metrics.impression_count} | Likes: ${metrics.like_count} | ` +
              `Retweets: ${metrics.retweet_count} | Replies: ${metrics.reply_count} | Quotes: ${metrics.quote_count}`,
              "",
              `URL: ${url}`,
            ].join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_get_tweet", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching tweet: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
