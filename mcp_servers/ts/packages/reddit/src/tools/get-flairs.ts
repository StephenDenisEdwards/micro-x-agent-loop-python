import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

export function registerGetFlairs(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_get_flairs",
    {
      description: "Get available post flair templates for a subreddit.",
      inputSchema: {
        subreddit: z.string().min(1).describe("Subreddit name (without r/ prefix)"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "reddit_get_flairs", request_id: requestId, subreddit: input.subreddit }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        const response = await resilientFetch(
          `https://oauth.reddit.com/r/${input.subreddit}/api/link_flair_v2`,
          {
            headers: {
              "Authorization": `Bearer ${auth.accessToken}`,
              "User-Agent": userAgent,
            },
          },
          { timeoutMs: 15_000, retries: 2 },
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `Reddit API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        const flairs = await response.json() as Array<{
          id: string;
          text: string;
          text_editable: boolean;
          type: string;
          background_color: string;
          text_color: string;
          mod_only: boolean;
          allowable_content: string;
        }>;

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_get_flairs", request_id: requestId, duration_ms: durationMs, outcome: "success", flair_count: flairs.length },
          "tool_call_end",
        );

        const mapped = flairs.map(f => ({
          flair_id: f.id,
          text: f.text,
          text_editable: f.text_editable,
          type: f.type,
          mod_only: f.mod_only,
          background_color: f.background_color,
          text_color: f.text_color,
        }));

        const result = {
          subreddit: input.subreddit,
          flairs: mapped,
          flair_count: mapped.length,
        };

        const lines = mapped
          .filter(f => !f.mod_only)
          .map(f => {
            const editable = f.text_editable ? " (editable)" : "";
            return `- ${f.text}${editable} [id: ${f.flair_id}]`;
          });

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: mapped.length > 0
              ? `Flairs for r/${input.subreddit} (${mapped.length}):\n\n${lines.join("\n")}`
              : `No post flairs available for r/${input.subreddit}.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "reddit_get_flairs", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching flairs: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
