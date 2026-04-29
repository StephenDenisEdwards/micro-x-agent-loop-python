import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getGmailService } from "../auth/google-auth.js";

function getHeader(headers: Array<{ name?: string; value?: string }> | undefined, name: string): string {
  if (!headers) return "";
  for (const h of headers) {
    if ((h.name ?? "").toLowerCase() === name.toLowerCase()) {
      return h.value ?? "";
    }
  }
  return "";
}

export function registerGmailSearch(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "gmail_search",
    {
      description:
        "Search Gmail using Gmail search syntax (e.g. 'is:unread', " +
        "'from:someone@example.com', 'subject:hello'). Returns a list of matching " +
        "emails with ID, date, from, subject, and snippet.",
      inputSchema: {
        query: z.string().describe("Gmail search query (e.g. 'is:unread', 'from:boss@co.com newer_than:7d')"),
        maxResults: z.number().optional().describe("Max number of results (default 10)"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "gmail_search", request_id: requestId }, "tool_call_start");

      try {
        const gmail = await getGmailService(clientId, clientSecret);
        const maxResults = input.maxResults ?? 10;

        const listResponse = await gmail.users.messages.list({
          userId: "me",
          q: input.query,
          maxResults,
        });

        const messages = listResponse.data.messages ?? [];
        if (messages.length === 0) {
          const durationMs = Date.now() - startTime;
          logger.info(
            { tool: "gmail_search", request_id: requestId, duration_ms: durationMs, outcome: "success", count: 0 },
            "tool_call_end",
          );
          return {
            content: [{ type: "text" as const, text: "No emails found matching your query." }],
          };
        }

        const structured: Array<{ id: string; date: string; from: string; subject: string; snippet: string }> = [];
        const textLines: string[] = [];
        for (const msg of messages) {
          if (!msg.id) continue;

          const detail = await gmail.users.messages.get({
            userId: "me",
            id: msg.id,
            format: "metadata",
            metadataHeaders: ["From", "Subject", "Date"],
          });

          const headers = detail.data.payload?.headers as Array<{ name?: string; value?: string }> | undefined;
          const fromAddr = getHeader(headers, "From");
          const subject = getHeader(headers, "Subject");
          const date = getHeader(headers, "Date");
          const snippet = detail.data.snippet ?? "";

          structured.push({ id: msg.id, date, from: fromAddr, subject, snippet });
          textLines.push(
            `ID: ${msg.id}\n` +
            `  Date: ${date}\n` +
            `  From: ${fromAddr}\n` +
            `  Subject: ${subject}\n` +
            `  Snippet: ${snippet}`,
          );
        }

        const text = textLines.join("\n\n");
        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "gmail_search", request_id: requestId, duration_ms: durationMs, outcome: "success", count: structured.length },
          "tool_call_end",
        );

        return {
          structuredContent: { messages: structured, total_found: structured.length },
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "gmail_search", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error searching Gmail: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
