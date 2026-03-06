import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getDraft, removeDraft } from "../draft-store.js";
import type { TweetDraft, ThreadDraft } from "../draft-store.js";
import { getXClient } from "../auth/x-auth.js";
import { uploadMedia } from "./upload-media.js";

const TWEETS_URL = "https://api.x.com/2/tweets";

interface PostedTweet {
  tweet_id: string;
  text: string;
}

export function registerPublishDraft(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "x_publish_draft",
    {
      description:
        "Publish a previously drafted tweet or thread. Requires a draft_id from " +
        "x_draft_tweet or x_draft_thread. Drafts expire after 10 minutes.",
      inputSchema: {
        draft_id: z.string().uuid().describe("Draft ID returned by x_draft_tweet or x_draft_thread"),
      },
      outputSchema: {
        success: z.boolean(),
        tweet_id: z.string().optional(),
        tweet_url: z.string().optional(),
        thread_url: z.string().optional(),
        tweets: z.array(z.object({
          tweet_id: z.string(),
          text: z.string(),
        })).optional(),
        posts_used: z.number().int(),
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

      logger.info({ tool: "x_publish_draft", request_id: requestId, draft_id: input.draft_id }, "tool_call_start");

      try {
        const draft = getDraft(input.draft_id);
        if (!draft) {
          const durationMs = Date.now() - startTime;
          logger.warn(
            { tool: "x_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "not_found", draft_id: input.draft_id },
            "tool_call_end",
          );
          return {
            content: [{
              type: "text" as const,
              text: "Draft not found or expired. Drafts expire after 10 minutes. Please create a new draft.",
            }],
            isError: true,
          };
        }

        const client = await getXClient(clientId, clientSecret);

        if (draft.type === "tweet") {
          const tweetDraft = draft.payload as TweetDraft;
          const result = await postTweet(client.accessToken, client.username, tweetDraft, logger);
          removeDraft(input.draft_id);

          const durationMs = Date.now() - startTime;
          logger.info(
            { tool: "x_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "success", tweet_id: result.tweet_id },
            "tool_call_end",
          );

          const structured = {
            success: true,
            tweet_id: result.tweet_id,
            tweet_url: result.url,
            posts_used: 1,
          };

          return {
            structuredContent: structured,
            content: [{
              type: "text" as const,
              text: `Published successfully!\n\nTweet ID: ${result.tweet_id}\nURL: ${result.url}`,
            }],
          };
        }

        // Thread
        const threadDraft = draft.payload as ThreadDraft;
        const posted: PostedTweet[] = [];
        let previousTweetId: string | undefined;

        for (let i = 0; i < threadDraft.tweets.length; i++) {
          const tweet = threadDraft.tweets[i];
          try {
            const tweetPayload: TweetDraft = {
              text: tweet.text,
              media_paths: tweet.media_paths,
              reply_to_id: previousTweetId,
            };
            const result = await postTweet(client.accessToken, client.username, tweetPayload, logger);
            posted.push({ tweet_id: result.tweet_id, text: tweet.text });
            previousTweetId = result.tweet_id;
          } catch (err: unknown) {
            // Partial failure — return what was posted + the error
            const message = err instanceof Error ? err.message : String(err);
            removeDraft(input.draft_id);

            const durationMs = Date.now() - startTime;
            logger.error(
              { tool: "x_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "partial_failure", tweets_posted: posted.length, total_tweets: threadDraft.tweets.length, error_message: message },
              "tool_call_end",
            );

            const threadUrl = posted.length > 0
              ? `https://x.com/${client.username}/status/${posted[0].tweet_id}`
              : undefined;

            return {
              structuredContent: {
                success: false,
                thread_url: threadUrl,
                tweets: posted,
                posts_used: posted.length,
              },
              content: [{
                type: "text" as const,
                text: `Thread partially published (${posted.length}/${threadDraft.tweets.length} tweets).\n` +
                  `Error on tweet ${i + 1}: ${message}\n` +
                  (threadUrl ? `Thread URL: ${threadUrl}` : ""),
              }],
              isError: true,
            };
          }
        }

        removeDraft(input.draft_id);

        const threadUrl = `https://x.com/${client.username}/status/${posted[0].tweet_id}`;
        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "success", tweet_count: posted.length },
          "tool_call_end",
        );

        const structured = {
          success: true,
          thread_url: threadUrl,
          tweets: posted,
          posts_used: posted.length,
        };

        return {
          structuredContent: structured,
          content: [{
            type: "text" as const,
            text: `Thread published successfully! (${posted.length} tweets)\n\nThread URL: ${threadUrl}`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error publishing draft: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

async function postTweet(
  accessToken: string,
  username: string,
  draft: TweetDraft,
  logger: Logger,
): Promise<{ tweet_id: string; text: string; url: string }> {
  // Upload media if present
  let mediaIds: string[] | undefined;
  if (draft.media_paths?.length) {
    mediaIds = [];
    for (const filePath of draft.media_paths) {
      const mediaId = await uploadMedia(accessToken, filePath, undefined, logger);
      mediaIds.push(mediaId);
    }
  }

  // Build tweet payload
  const body: Record<string, unknown> = {
    text: draft.text,
  };

  if (draft.reply_to_id) {
    body.reply = { in_reply_to_tweet_id: draft.reply_to_id };
  }

  if (draft.quote_tweet_id) {
    body.quote_tweet_id = draft.quote_tweet_id;
  }

  if (mediaIds?.length) {
    body.media = { media_ids: mediaIds };
  }

  const response = await resilientFetch(
    TWEETS_URL,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    },
    { timeoutMs: 15_000, retries: 1 },
  );

  // X returns 201 on success, not 200
  if (response.status !== 201) {
    const errorText = await response.text();
    throw new UpstreamError(
      `X API error (${response.status}): ${errorText}`,
      response.status,
    );
  }

  const data = await response.json() as {
    data: { id: string; text: string };
  };

  return {
    tweet_id: data.data.id,
    text: data.data.text,
    url: `https://x.com/${username}/status/${data.data.id}`,
  };
}
