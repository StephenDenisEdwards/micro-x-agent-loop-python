import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
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
 */
function decodeBody(data: string): string {
  // Gmail uses base64url encoding (no padding, - and _ instead of + and /)
  const base64 = data.replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(base64, "base64").toString("utf-8");
}

/**
 * Simple HTML to text conversion.
 * Strips tags, decodes entities, normalizes whitespace.
 */
function htmlToText(html: string): string {
  let text = html;
  // Remove script and style blocks
  text = text.replace(/<script[\s\S]*?<\/script>/gi, "");
  text = text.replace(/<style[\s\S]*?<\/style>/gi, "");
  // Convert <br> to newlines
  text = text.replace(/<br\s*\/?>/gi, "\n");
  // Convert block elements to newlines
  text = text.replace(/<\/(p|div|tr|h[1-6]|blockquote|li)>/gi, "\n");
  text = text.replace(/<(p|div|tr|h[1-6]|blockquote)[\s>]/gi, "\n");
  // Convert list items
  text = text.replace(/<li[\s>]/gi, "\n- ");
  // Preserve link URLs: extract href and text
  text = text.replace(/<a\s+[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi, (_, href: string, linkText: string) => {
    const cleanText = linkText.replace(/<[^>]+>/g, "").trim();
    if (href && href !== cleanText && !href.startsWith("#")) {
      return cleanText ? `${cleanText} ${href}` : href;
    }
    return cleanText;
  });
  // Strip remaining tags
  text = text.replace(/<[^>]+>/g, "");
  // Decode common HTML entities
  text = text.replace(/&amp;/g, "&");
  text = text.replace(/&lt;/g, "<");
  text = text.replace(/&gt;/g, ">");
  text = text.replace(/&quot;/g, '"');
  text = text.replace(/&#39;/g, "'");
  text = text.replace(/&nbsp;/g, " ");
  // Normalize whitespace
  text = text.replace(/[ \t]{3,}/g, "  ");
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
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
