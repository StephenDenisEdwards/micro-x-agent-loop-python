import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { createDraft } from "../draft-store.js";
import { parseTweetText } from "../char-count.js";

export function registerDraftTweet(
  server: McpServer,
  logger: Logger,
): void {
  server.registerTool(
    "x_draft_tweet",
    {
      description:
        "Create a draft tweet for review before publishing. " +
        "Returns a draft_id and preview. Does NOT post to X. " +
        "Use x_publish_draft with the draft_id to publish.",
      inputSchema: {
        text: z.string().min(1).describe("Tweet text (max 280 chars; URLs count as 23 chars)"),
        reply_to_id: z.string().optional().describe("Tweet ID to reply to"),
        quote_tweet_id: z.string().optional().describe("Tweet ID to quote"),
        media_paths: z.array(z.string()).max(4).optional().describe("Local paths to images (max 4)"),
      },
      outputSchema: {
        draft_id: z.string(),
        preview: z.string(),
        weighted_length: z.number().int(),
        max_length: z.number().int(),
        is_valid_length: z.boolean(),
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

      logger.info({ tool: "x_draft_tweet", request_id: requestId }, "tool_call_start");

      try {
        // Validate mutual exclusivity: quote_tweet_id and media_paths cannot be combined
        if (input.quote_tweet_id && input.media_paths?.length) {
          return {
            content: [{
              type: "text" as const,
              text: "Error: Cannot combine quote tweet with media attachments in a single tweet.",
            }],
            isError: true,
          };
        }

        // Character count validation
        const parsed = parseTweetText(input.text);
        if (!parsed.isValid) {
          return {
            content: [{
              type: "text" as const,
              text: `Error: Tweet exceeds character limit. Weighted length: ${parsed.weightedLength}/${parsed.maxLength}`,
            }],
            isError: true,
          };
        }

        // Build preview
        const lines: string[] = ["[Draft Tweet]", ""];
        if (input.reply_to_id) {
          lines.push(`Replying to tweet ${input.reply_to_id}`);
        }
        if (input.quote_tweet_id) {
          lines.push(`Quoting tweet ${input.quote_tweet_id}`);
        }
        lines.push(input.text);
        if (input.media_paths?.length) {
          lines.push("", `Media: ${input.media_paths.length} file(s)`);
          for (const p of input.media_paths) {
            lines.push(`  - ${p}`);
          }
        }
        lines.push("", `Characters: ${parsed.weightedLength}/${parsed.maxLength}`);

        const preview = lines.join("\n");
        const draftId = createDraft("tweet", {
          text: input.text,
          reply_to_id: input.reply_to_id,
          quote_tweet_id: input.quote_tweet_id,
          media_paths: input.media_paths,
        }, preview);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_draft_tweet", request_id: requestId, duration_ms: durationMs, outcome: "success", draft_id: draftId },
          "tool_call_end",
        );

        const result = {
          draft_id: draftId,
          preview,
          weighted_length: parsed.weightedLength,
          max_length: parsed.maxLength,
          is_valid_length: parsed.isValid,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: `Draft created (${draftId}).\n\n${preview}\n\nUse x_publish_draft with this draft_id to publish.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_draft_tweet", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating draft tweet: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
