import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { ValidationError, UpstreamError } from "@micro-x/mcp-shared";
import { htmlToText } from "../html-to-text.js";

const DEFAULT_MAX_CHARS = 50_000;
const MAX_RESPONSE_BYTES = 2_000_000; // 2 MB
const TIMEOUT_MS = 30_000;
const MAX_REDIRECTS = 5;

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

const HEADERS: Record<string, string> = {
  "User-Agent": USER_AGENT,
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.5",
};

export function registerWebFetch(server: McpServer, logger: Logger): void {
  server.registerTool(
    "web_fetch",
    {
      description:
        "Fetch content from a URL and return it as readable text. " +
        "Supports HTML pages (converted to plain text with links preserved), " +
        "JSON APIs (pretty-printed), and plain text. GET requests only.",
      inputSchema: {
        url: z.string().min(1).describe("The HTTP or HTTPS URL to fetch"),
        maxChars: z
          .number()
          .int()
          .min(1)
          .default(DEFAULT_MAX_CHARS)
          .describe(
            `Maximum characters of content to return (default ${DEFAULT_MAX_CHARS}). Content beyond this limit is truncated with a notice.`,
          )
          .optional(),
      },
      outputSchema: {
        url: z.string(),
        final_url: z.string(),
        status_code: z.number().int(),
        content_type: z.string(),
        title: z.string(),
        content: z.string(),
        content_length: z.number().int(),
        truncated: z.boolean(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const maxChars = input.maxChars ?? DEFAULT_MAX_CHARS;

      logger.info({ tool: "web_fetch", request_id: requestId, url: input.url }, "tool_call_start");

      try {
        // Validate URL scheme
        let parsedUrl: URL;
        try {
          parsedUrl = new URL(input.url);
        } catch {
          throw new ValidationError("Invalid URL format");
        }

        if (parsedUrl.protocol !== "http:" && parsedUrl.protocol !== "https:") {
          throw new ValidationError("URL must use http or https scheme");
        }

        // Fetch with redirect following
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

        let response: Response;
        try {
          response = await fetch(input.url, {
            headers: HEADERS,
            signal: controller.signal,
            redirect: "follow",
          });
        } catch (err: unknown) {
          if (err instanceof Error && err.name === "AbortError") {
            throw new UpstreamError(`Request timed out after ${TIMEOUT_MS / 1000} seconds`);
          }
          throw new UpstreamError(err instanceof Error ? err.message : String(err));
        } finally {
          clearTimeout(timeout);
        }

        if (response.status >= 400) {
          throw new UpstreamError(`HTTP ${response.status} fetching ${input.url}`, response.status);
        }

        // Read body with size check
        const arrayBuffer = await response.arrayBuffer();
        if (arrayBuffer.byteLength > MAX_RESPONSE_BYTES) {
          throw new UpstreamError(
            `Response too large (${arrayBuffer.byteLength.toLocaleString()} bytes, max ${MAX_RESPONSE_BYTES.toLocaleString()} bytes)`,
          );
        }

        const bodyText = new TextDecoder("utf-8", { fatal: false }).decode(arrayBuffer);
        const contentType = response.headers.get("content-type") ?? "";
        const finalUrl = response.url || input.url;

        // Extract content based on content type
        let content: string;
        let title = "";

        if (contentType.includes("text/html") || contentType.includes("application/xhtml")) {
          const result = htmlToText(bodyText);
          content = result.text;
          title = result.title;
        } else if (contentType.includes("application/json")) {
          try {
            content = JSON.stringify(JSON.parse(bodyText), null, 2);
          } catch {
            content = bodyText;
          }
        } else {
          content = bodyText;
        }

        // Truncate if needed
        const originalLength = content.length;
        let truncated = false;
        if (originalLength > maxChars) {
          content = content.slice(0, maxChars);
          truncated = true;
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          {
            tool: "web_fetch",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "success",
            status_code: response.status,
            content_length: originalLength,
            truncated,
          },
          "tool_call_end",
        );

        // Build text output (matching Python format)
        const textParts = [`URL: ${input.url}`];
        if (finalUrl !== input.url) textParts.push(`Final URL: ${finalUrl}`);
        textParts.push(`Status: ${response.status}`);
        textParts.push(`Content-Type: ${contentType}`);
        if (title) textParts.push(`Title: ${title}`);

        const lengthStr = truncated
          ? `${maxChars.toLocaleString()} chars (truncated from ${originalLength.toLocaleString()})`
          : `${originalLength.toLocaleString()} chars`;
        textParts.push(`Length: ${lengthStr}`);
        textParts.push("");
        textParts.push("--- Content ---");
        textParts.push("");
        textParts.push(content);
        if (truncated) {
          textParts.push("");
          textParts.push(`[Content truncated at ${maxChars.toLocaleString()} characters]`);
        }

        const structured = {
          url: input.url,
          final_url: finalUrl,
          status_code: response.status,
          content_type: contentType,
          title,
          content,
          content_length: originalLength,
          truncated,
        };

        return {
          structuredContent: { ...structured },
          content: [{ type: "text" as const, text: textParts.join("\n") }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);
        const errorCode =
          err instanceof ValidationError ? "validation_error" : err instanceof UpstreamError ? "upstream_error" : "internal_error";

        logger.error(
          { tool: "web_fetch", request_id: requestId, duration_ms: durationMs, outcome: "error", error_code: errorCode, error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
