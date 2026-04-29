import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { createDraft } from "../draft-store.js";
import { parseTweetText } from "../char-count.js";

export function registerDraftThread(
  server: McpServer,
  logger: Logger,
): void {
  server.registerTool(
    "x_draft_thread",
    {
      description:
        "Create a draft thread (multiple tweets) for review before publishing. " +
        "Validates all tweets for character limits. Each tweet in a thread counts " +
        "against the monthly post quota independently. " +
        "Use x_publish_draft with the draft_id to publish.",
      inputSchema: {
        tweets: z.array(
          z.object({
            text: z.string().min(1).describe("Tweet text"),
            media_paths: z.array(z.string()).max(4).optional().describe("Local paths to images (max 4)"),
          }),
        ).min(2).max(25).describe("Array of tweets in order (min 2, max 25)"),
      },
      outputSchema: {
        draft_id: z.string(),
        preview: z.string(),
        tweet_count: z.number().int(),
        tweets_detail: z.array(z.object({
          index: z.number().int(),
          weighted_length: z.number().int(),
          is_valid: z.boolean(),
        })),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "x_draft_thread", request_id: requestId }, "tool_call_start");

      try {
        const tweetsDetail: Array<{ index: number; weighted_length: number; is_valid: boolean }> = [];
        const invalidTweets: number[] = [];

        // Validate all tweets
        for (let i = 0; i < input.tweets.length; i++) {
          const tweet = input.tweets[i];
          const parsed = parseTweetText(tweet.text);
          tweetsDetail.push({
            index: i + 1,
            weighted_length: parsed.weightedLength,
            is_valid: parsed.isValid,
          });
          if (!parsed.isValid) {
            invalidTweets.push(i + 1);
          }
        }

        if (invalidTweets.length > 0) {
          return {
            content: [{
              type: "text" as const,
              text: `Error: Tweet(s) ${invalidTweets.join(", ")} exceed the 280-character limit.\n\n` +
                tweetsDetail.map(t => `  Tweet ${t.index}: ${t.weighted_length}/280${t.is_valid ? "" : " (OVER LIMIT)"}`).join("\n"),
            }],
            isError: true,
          };
        }

        // Build preview
        const lines: string[] = [`[Draft Thread — ${input.tweets.length} tweets]`, ""];
        for (let i = 0; i < input.tweets.length; i++) {
          const tweet = input.tweets[i];
          const detail = tweetsDetail[i];
          lines.push(`--- Tweet ${i + 1}/${input.tweets.length} (${detail.weighted_length}/280) ---`);
          lines.push(tweet.text);
          if (tweet.media_paths?.length) {
            lines.push(`Media: ${tweet.media_paths.length} file(s)`);
          }
          lines.push("");
        }
        lines.push(`Quota impact: This thread will use ${input.tweets.length} of your monthly posts.`);

        const preview = lines.join("\n");
        const draftId = createDraft("thread", {
          tweets: input.tweets,
        }, preview);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_draft_thread", request_id: requestId, duration_ms: durationMs, outcome: "success", draft_id: draftId, tweet_count: input.tweets.length },
          "tool_call_end",
        );

        const result = {
          draft_id: draftId,
          preview,
          tweet_count: input.tweets.length,
          tweets_detail: tweetsDetail,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: `Thread draft created (${draftId}).\n\n${preview}\nUse x_publish_draft with this draft_id to publish.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_draft_thread", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating draft thread: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
