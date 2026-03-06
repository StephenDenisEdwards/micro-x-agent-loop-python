import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getXClient } from "../auth/x-auth.js";

export function registerDeleteTweet(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "x_delete_tweet",
    {
      description: "Delete a tweet by ID.",
      inputSchema: {
        tweet_id: z.string().min(1).describe("ID of the tweet to delete"),
      },
      outputSchema: {
        success: z.boolean(),
        tweet_id: z.string(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "x_delete_tweet", request_id: requestId, tweet_id: input.tweet_id }, "tool_call_start");

      try {
        const client = await getXClient(clientId, clientSecret);

        const response = await resilientFetch(
          `https://api.x.com/2/tweets/${input.tweet_id}`,
          {
            method: "DELETE",
            headers: {
              "Authorization": `Bearer ${client.accessToken}`,
            },
          },
          { timeoutMs: 15_000, retries: 1 },
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `X API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        const data = await response.json() as { data: { deleted: boolean } };

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_delete_tweet", request_id: requestId, duration_ms: durationMs, outcome: "success", tweet_id: input.tweet_id },
          "tool_call_end",
        );

        const result = {
          success: data.data.deleted,
          tweet_id: input.tweet_id,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: data.data.deleted
              ? `Tweet ${input.tweet_id} deleted successfully.`
              : `Tweet ${input.tweet_id} could not be deleted.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_delete_tweet", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error deleting tweet: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
