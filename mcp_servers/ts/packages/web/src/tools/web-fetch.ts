import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { ValidationError, UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";
import { htmlToText } from "../html-to-text.js";

const MAX_RESPONSE_BYTES = 2_000_000; // 2 MB — hard safety cap on raw bytes
const TIMEOUT_MS = 30_000;

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
        "Fetch a STATIC resource via HTTP GET and return it as text. " +
        "Use only for plain HTML with no JavaScript, JSON/REST APIs, RSS feeds, robots.txt, " +
        "or other text endpoints. Does NOT execute JavaScript, follow auth flows, " +
        "or render single-page apps — for those, use the browser_* tools (Playwright) instead. " +
        "If the response from this tool looks empty or JS-skeleton, switch to browser_navigate. " +
        "Pass `save_to_file` when you intend to grep/count/filter the result rather than read it — " +
        "the extracted content is written to that path and only metadata comes back, keeping the " +
        "conversation context small. Plain `web_fetch` (no `save_to_file`) returns the full content " +
        "inline for cases where you need to read it.",
      inputSchema: {
        url: z.string().min(1).describe("The HTTP or HTTPS URL to fetch"),
        maxChars: z
          .number()
          .int()
          .min(1)
          .describe(
            "Optional cap on returned content characters. If omitted, the full extracted content is returned (subject only to the 2 MB raw-response byte cap). The agent applies its own `ToolResultOverrides` policy on top of whatever this tool returns.",
          )
          .optional(),
        save_to_file: z
          .string()
          .min(1)
          .describe(
            "Optional filesystem path (absolute, or relative to the MCP server's working directory). When set, the extracted content is written to this path and the response body contains only metadata (no content). Use when you intend to operate on the data (grep/count/filter) rather than read it. Parent directories are created if missing; the file is overwritten if it exists.",
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
        saved_to: z.string().optional(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const maxChars = input.maxChars;
      const saveToFile = input.save_to_file;

      logger.info(
        { tool: "web_fetch", request_id: requestId, url: input.url, save_to_file: saveToFile },
        "tool_call_start",
      );

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

        // Resolve save_to_file against the MCP server's working directory if
        // it's a relative path. The agent's mcp_manager sets cwd to the
        // workspace working dir, so this matches what filesystem__grep and
        // read_file see.
        const resolvedSaveToFile = saveToFile !== undefined
          ? resolve(process.cwd(), saveToFile)
          : undefined;

        // Fetch with redirect following, timeout, and retry on transient errors
        const response = await resilientFetch(input.url, {
          headers: HEADERS,
          redirect: "follow",
        }, { timeoutMs: TIMEOUT_MS, retries: 3 });

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

        // Truncate only when the caller explicitly requests a cap.
        // Otherwise return the full extracted content; the agent's
        // `ToolResultOverrides` is the authoritative truncation layer.
        const originalLength = content.length;
        let truncated = false;
        if (maxChars !== undefined && originalLength > maxChars) {
          content = content.slice(0, maxChars);
          truncated = true;
        }

        // save_to_file: write extracted content to disk and return metadata
        // only — keeps the conversation small for grep/count/filter workflows.
        // Parent dirs are created if missing; relative paths are resolved
        // against the MCP server's working directory (see resolvedSaveToFile).
        let savedTo: string | undefined;
        if (resolvedSaveToFile !== undefined) {
          try {
            await mkdir(dirname(resolvedSaveToFile), { recursive: true });
            await writeFile(resolvedSaveToFile, content, "utf-8");
            savedTo = resolvedSaveToFile;
          } catch (err) {
            throw new UpstreamError(
              `Failed to write content to ${resolvedSaveToFile}: ${err instanceof Error ? err.message : String(err)}`,
            );
          }
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
            saved_to: savedTo,
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
          ? `${content.length.toLocaleString()} chars (truncated from ${originalLength.toLocaleString()})`
          : `${originalLength.toLocaleString()} chars`;
        textParts.push(`Length: ${lengthStr}`);

        if (savedTo !== undefined) {
          // Metadata-only mode: omit --- Content --- section
          textParts.push(`Saved to: ${savedTo}`);
        } else {
          textParts.push("");
          textParts.push("--- Content ---");
          textParts.push("");
          textParts.push(content);
          if (truncated) {
            textParts.push("");
            textParts.push(`[Content truncated at ${content.length.toLocaleString()} characters]`);
          }
        }

        const structured = {
          url: input.url,
          final_url: finalUrl,
          status_code: response.status,
          content_type: contentType,
          title,
          // In save_to_file mode, content stays empty so the file is the
          // canonical place to read from; in inline mode it carries the data.
          content: savedTo !== undefined ? "" : content,
          content_length: originalLength,
          truncated,
          ...(savedTo !== undefined ? { saved_to: savedTo } : {}),
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
