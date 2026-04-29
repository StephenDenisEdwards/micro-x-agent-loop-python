import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

const EDIT_URL = "https://oauth.reddit.com/api/editusertext";

export function registerEdit(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_edit",
    {
      description: "Edit the text body of your own Reddit post or comment.",
      inputSchema: {
        fullname: z.string().min(1).describe("Fullname of the post (t3_) or comment (t1_) to edit"),
        text: z.string().min(1).describe("New text content (Markdown supported)"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "reddit_edit", request_id: requestId, fullname: input.fullname }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        const response = await resilientFetch(
          EDIT_URL,
          {
            method: "POST",
            headers: {
              "Authorization": `Bearer ${auth.accessToken}`,
              "User-Agent": userAgent,
              "Content-Type": "application/x-www-form-urlencoded",
            },
            body: new URLSearchParams({
              api_type: "json",
              thing_id: input.fullname,
              text: input.text,
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

        const data = await response.json() as {
          json: {
            errors: Array<[string, string, string]>;
            data?: {
              things: Array<{
                data: {
                  name: string;
                  body: string;
                };
              }>;
            };
          };
        };

        if (data.json.errors && data.json.errors.length > 0) {
          const errorMessages = data.json.errors.map(e => `${e[0]}: ${e[1]}`).join("; ");
          const durationMs = Date.now() - startTime;
          logger.error(
            { tool: "reddit_edit", request_id: requestId, duration_ms: durationMs, outcome: "api_error", errors: errorMessages },
            "tool_call_end",
          );
          return {
            content: [{
              type: "text" as const,
              text: `Reddit rejected the edit: ${errorMessages}`,
            }],
            isError: true,
          };
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_edit", request_id: requestId, duration_ms: durationMs, outcome: "success", fullname: input.fullname },
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
            text: `Successfully edited ${input.fullname}.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "reddit_edit", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error editing: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
