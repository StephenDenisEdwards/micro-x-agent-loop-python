import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getGmailService } from "../auth/google-auth.js";

export function registerGmailSend(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "gmail_send",
    {
      description: "Send an email from your Gmail account.",
      inputSchema: {
        to: z.string().describe("Recipient email address"),
        subject: z.string().describe("Email subject line"),
        body: z.string().describe("Email body (plain text)"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "gmail_send", request_id: requestId }, "tool_call_start");

      try {
        const gmail = await getGmailService(clientId, clientSecret);

        const messageText =
          `To: ${input.to}\r\n` +
          `Subject: ${input.subject}\r\n` +
          `Content-Type: text/plain; charset=utf-8\r\n` +
          `\r\n` +
          input.body;

        // Gmail API expects base64url encoding without padding
        const raw = Buffer.from(messageText, "utf-8")
          .toString("base64")
          .replace(/\+/g, "-")
          .replace(/\//g, "_")
          .replace(/=+$/, "");

        const result = await gmail.users.messages.send({
          userId: "me",
          requestBody: { raw },
        });

        const sentId = result.data.id ?? "unknown";
        const text = `Email sent successfully (ID: ${sentId})`;

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "gmail_send", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "gmail_send", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error sending email: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
