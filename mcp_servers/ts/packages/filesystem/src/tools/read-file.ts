import { readFile } from "node:fs/promises";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { resolveAllowed, type PathPolicy } from "../paths.js";

const DEFAULT_LIMIT = 2000;
const MAX_LIMIT = 10000;
const BINARY_SNIFF_BYTES = 8 * 1024;
const LINE_NUM_WIDTH = 6;

export function registerReadFile(server: McpServer, logger: Logger, policy: PathPolicy): void {
  server.registerTool(
    "read_file",
    {
      description:
        "Read a file as cat -n-style line-numbered text. Supports plain text and .docx documents. " +
        "PREFER `grep` even when you know the path — if you only need specific lines, headings, or patterns " +
        "(e.g. \"list the headings\", \"find the Score lines\", \"extract all links\"), grep returns just the matches " +
        "instead of the whole file. Use read_file when you genuinely need the file's full content, are reading " +
        "top-to-bottom for comprehension, or need to discover the file's structure before targeted extraction " +
        "(in which case slice with offset=1, limit=60 first, then switch to grep). " +
        "Use offset and limit for large files — by default the first 2000 lines are returned. " +
        "Quote `<path>:<line>` coordinates from the output when referring back to the file or feeding into edit_file. " +
        "Path must be inside FILESYSTEM_WORKING_DIR or FILESYSTEM_ALLOWED_DIRS — absolute paths outside the allowed roots are rejected. " +
        "Binary files are refused (null-byte sniff over the first 8 KB).",
      inputSchema: {
        path: z.string().min(1).describe("Absolute or relative path to the file to read"),
        offset: z.number().int().min(1).optional().describe("1-based line number to start reading from. Default: 1"),
        limit: z.number().int().min(1).max(MAX_LIMIT).optional().describe(`Max lines to return. Default: ${DEFAULT_LIMIT}, hard max: ${MAX_LIMIT}`),
      },
      outputSchema: {
        content: z.string(),
        path: z.string(),
        size_bytes: z.number().int(),
        total_lines: z.number().int(),
        start_line: z.number().int(),
        end_line: z.number().int(),
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
      const offset = input.offset ?? 1;
      const limit = input.limit ?? DEFAULT_LIMIT;

      logger.info(
        { tool: "read_file", request_id: requestId, path: input.path, offset, limit },
        "tool_call_start",
      );

      try {
        const resolvedPath = await resolveAllowed(policy, input.path, { mustExist: true });

        let rawText: string;
        if (resolvedPath.toLowerCase().endsWith(".docx")) {
          // .docx is a zip; binary detection would always reject it. Skip the check
          // and let mammoth surface decode errors if the file is malformed.
          rawText = await readDocx(resolvedPath);
        } else {
          const buf = await readFile(resolvedPath);
          if (isBinary(buf)) {
            const msg = `refusing to read binary file: ${resolvedPath} (null byte detected in first ${BINARY_SNIFF_BYTES} bytes)`;
            logger.warn({ tool: "read_file", request_id: requestId, path: resolvedPath }, "binary_refused");
            return {
              content: [{ type: "text" as const, text: msg }],
              isError: true,
            };
          }
          rawText = buf.toString("utf-8");
        }

        const allLines = splitLines(rawText);
        const totalLines = allLines.length;
        const sizeBytes = Buffer.byteLength(rawText, "utf-8");

        const startIndex = offset - 1;
        const endIndex = Math.min(startIndex + limit, totalLines);
        const slicedLines = startIndex < totalLines ? allLines.slice(startIndex, endIndex) : [];
        const startLine = slicedLines.length > 0 ? offset : 0;
        const endLine = slicedLines.length > 0 ? offset + slicedLines.length - 1 : 0;
        const truncated = endIndex < totalLines;

        let formatted: string;
        if (totalLines === 0) {
          formatted = "(file is empty)";
        } else if (slicedLines.length === 0) {
          formatted = `(offset ${offset} is past end of file — file has ${totalLines} lines)`;
        } else {
          const formattedLines = slicedLines.map((line, i) => {
            const lineNum = String(offset + i).padStart(LINE_NUM_WIDTH, " ");
            return `${lineNum}\t${line}`;
          });
          formatted = formattedLines.join("\n");
          if (truncated) {
            const shownBytes = Buffer.byteLength(slicedLines.join("\n"), "utf-8");
            const linePct = Math.max(1, Math.round((slicedLines.length / totalLines) * 100));
            const nextOffset = endLine + 1;
            formatted +=
              `\n\n[Output truncated: showed lines ${startLine}-${endLine} of ${totalLines} ` +
              `(${linePct}%, ${formatBytes(shownBytes)} of ${formatBytes(sizeBytes)}).\n` +
              ` To read more: read_file(path="${resolvedPath}", offset=${nextOffset}, limit=${limit})]`;
          }
        }
        const durationMs = Date.now() - startTime;
        logger.info(
          {
            tool: "read_file",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "success",
            size_bytes: sizeBytes,
            total_lines: totalLines,
            returned_lines: slicedLines.length,
            truncated,
          },
          "tool_call_end",
        );

        return {
          structuredContent: {
            content: formatted,
            path: resolvedPath,
            size_bytes: sizeBytes,
            total_lines: totalLines,
            start_line: startLine,
            end_line: endLine,
            truncated,
          },
          content: [{ type: "text" as const, text: formatted }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "read_file", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error reading file: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

function isBinary(buf: Buffer): boolean {
  const len = Math.min(buf.length, BINARY_SNIFF_BYTES);
  for (let i = 0; i < len; i++) {
    if (buf[i] === 0) return true;
  }
  return false;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}KB`;
  return `${(n / (1024 * 1024)).toFixed(1)}MB`;
}

function splitLines(text: string): string[] {
  if (text === "") return [];
  const lines = text.split("\n");
  // A trailing newline produces a phantom empty element — drop it so total_lines
  // matches what `wc -l` would report for a well-formed text file.
  if (lines.length > 0 && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

async function readDocx(filePath: string): Promise<string> {
  const mammoth = await import("mammoth");
  const result = await mammoth.default.extractRawText({ path: filePath });
  return result.value;
}
