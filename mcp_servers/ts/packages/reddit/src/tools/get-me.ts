import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

export function registerGetMe(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_get_me",
    {
      description: "Get the authenticated Reddit user's profile information.",
      inputSchema: {},
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async () => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "reddit_get_me", request_id: requestId }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        const response = await resilientFetch(
          "https://oauth.reddit.com/api/v1/me",
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

        const data = await response.json() as {
          name: string;
          id: string;
          created_utc: number;
          link_karma: number;
          comment_karma: number;
          total_karma: number;
          has_verified_email: boolean;
          is_gold: boolean;
          is_mod: boolean;
          icon_img: string;
          subreddit?: {
            display_name_prefixed: string;
            subscribers: number;
          };
        };

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_get_me", request_id: requestId, duration_ms: durationMs, outcome: "success", username: data.name },
          "tool_call_end",
        );

        const result = {
          username: data.name,
          user_id: data.id,
          created_utc: data.created_utc,
          link_karma: data.link_karma,
          comment_karma: data.comment_karma,
          total_karma: data.total_karma,
          has_verified_email: data.has_verified_email,
          is_gold: data.is_gold,
          is_mod: data.is_mod,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: [
              `u/${data.name}`,
              `Account created: ${new Date(data.created_utc * 1000).toISOString()}`,
              `Total karma: ${data.total_karma} (link: ${data.link_karma}, comment: ${data.comment_karma})`,
              `Verified email: ${data.has_verified_email ? "Yes" : "No"}`,
              `Gold: ${data.is_gold ? "Yes" : "No"}`,
              `Moderator: ${data.is_mod ? "Yes" : "No"}`,
            ].join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "reddit_get_me", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching profile: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
