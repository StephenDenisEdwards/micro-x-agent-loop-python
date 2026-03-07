import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

const DELETE_URL = "https://oauth.reddit.com/api/del";

export function registerDelete(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_delete",
    {
      description: "Delete your own Reddit post or comment.",
      inputSchema: {
        fullname: z.string().min(1).describe("Fullname of the post (t3_) or comment (t1_) to delete"),
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

      logger.info({ tool: "reddit_delete", request_id: requestId, fullname: input.fullname }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        const response = await resilientFetch(
          DELETE_URL,
          {
            method: "POST",
            headers: {
              "Authorization": `Bearer ${auth.accessToken}`,
              "User-Agent": userAgent,
              "Content-Type": "application/x-www-form-urlencoded",
            },
            body: new URLSearchParams({
              id: input.fullname,
            }).toString(),
          },
          { timeoutMs: 15_000, retries: 1 },
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `Reddit API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_delete", request_id: requestId, duration_ms: durationMs, outcome: "success", fullname: input.fullname },
          "tool_call_end",
        );

        const result = {
          success: true,
          fullname: input.fullname,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: `Successfully deleted ${input.fullname}.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "reddit_delete", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error deleting: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
