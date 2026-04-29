import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { convert } from "html-to-text";
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

/**
 * Decode Gmail's base64url-encoded body data.
 * Tries UTF-8 first; falls back to Latin-1 if the result contains
 * replacement characters (common with UK emails using Windows-1252).
 */
function decodeBody(data: string): string {
  const base64 = data.replace(/-/g, "+").replace(/_/g, "/");
  const buf = Buffer.from(base64, "base64");
  const utf8 = buf.toString("utf-8");
  if (utf8.includes("\uFFFD")) {
    return buf.toString("latin1");
  }
  return utf8;
}

/**
 * Convert HTML to plain text using html-to-text library.
 * Preserves links as "text (url)" format, handles all entities and encodings.
 */
function htmlToText(html: string): string {
  return convert(html, {
    wordwrap: false,
    selectors: [
      { selector: "img", format: "skip" },
    ],
  });
}

interface GmailPayload {
  mimeType?: string;
  body?: { data?: string };
  parts?: GmailPayload[];
}

/**
 * Recursively extract the best text content from a Gmail message payload.
 * For multipart/alternative, prefer HTML (converted to text).
 * For other multipart types, concatenate all readable sub-parts.
 */
function extractText(payload: GmailPayload): string {
  const bodyData = payload.body?.data ?? "";
  const mimeType = payload.mimeType ?? "";

  if (bodyData) {
    if (mimeType === "text/plain") {
      return decodeBody(bodyData);
    }
    if (mimeType === "text/html") {
      return htmlToText(decodeBody(bodyData));
    }
  }

  const parts = payload.parts;
  if (!parts || parts.length === 0) {
    return "";
  }

  // multipart/alternative — pick the richest version
  if (mimeType === "multipart/alternative") {
    // Prefer HTML
    for (let i = parts.length - 1; i >= 0; i--) {
      const part = parts[i];
      if (part.mimeType === "text/html" && part.body?.data) {
        return htmlToText(decodeBody(part.body.data));
      }
    }

    // Try nested multipart
    for (let i = parts.length - 1; i >= 0; i--) {
      const part = parts[i];
      if ((part.mimeType ?? "").startsWith("multipart/")) {
        const text = extractText(part);
        if (text) return text;
      }
    }

    // Fall back to plain text
    for (const part of parts) {
      if (part.mimeType === "text/plain" && part.body?.data) {
        return decodeBody(part.body.data);
      }
    }
  }

  // multipart/mixed, multipart/related, etc.
  const sections: string[] = [];
  for (const part of parts) {
    const text = extractText(part);
    if (text) {
      sections.push(text);
    }
  }
  return sections.join("\n\n");
}

export function registerGmailRead(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "gmail_read",
    {
      description: "Read the full content of a Gmail email by its message ID (from gmail_search results).",
      inputSchema: {
        messageId: z.string().describe("The Gmail message ID (from gmail_search results)"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "gmail_read", request_id: requestId }, "tool_call_start");

      try {
        const gmail = await getGmailService(clientId, clientSecret);

        const message = await gmail.users.messages.get({
          userId: "me",
          id: input.messageId,
          format: "full",
        });

        const headers = message.data.payload?.headers as Array<{ name?: string; value?: string }> | undefined;
        const fromAddr = getHeader(headers, "From");
        const toAddr = getHeader(headers, "To");
        const subject = getHeader(headers, "Subject");
        const date = getHeader(headers, "Date");

        const payload = message.data.payload as GmailPayload | undefined;
        let body = payload ? extractText(payload) : "(no text content)";
        if (!body) {
          body = "(no text content)";
        }

        const text = `From: ${fromAddr}\nTo: ${toAddr}\nDate: ${date}\nSubject: ${subject}\n\n${body}`;

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "gmail_read", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          structuredContent: {
            messageId: input.messageId,
            from: fromAddr,
            to: toAddr,
            date,
            subject,
            body,
          },
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "gmail_read", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error reading email: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
