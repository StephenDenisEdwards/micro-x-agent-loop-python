import { appendFile, access } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";

export function registerAppendFile(server: McpServer, logger: Logger, workingDir: string): void {
  server.registerTool(
    "append_file",
    {
      description:
        "Append content to the end of a file. The file must already exist. " +
        "Use this to write large files in stages — create the file with write_file first, then append additional sections.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute or relative path to the file to append to"),
        content: z.string().describe("The content to append to the file"),
      },
      outputSchema: {
        success: z.boolean(),
        path: z.string(),
        appended_bytes: z.number().int(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "append_file", request_id: requestId, path: input.path }, "tool_call_start");

      try {
        const resolvedPath = path.isAbsolute(input.path)
          ? input.path
          : path.resolve(workingDir, input.path);

        // Check file exists (error if not)
        try {
          await access(resolvedPath);
        } catch {
          const msg = `Error: file does not exist: ${resolvedPath}. Use write_file to create it first.`;
          logger.warn({ tool: "append_file", request_id: requestId, path: resolvedPath }, "file_not_found");
          return {
            content: [{ type: "text" as const, text: msg }],
            isError: true,
          };
        }

        await appendFile(resolvedPath, input.content, "utf-8");

        const appendedBytes = Buffer.byteLength(input.content, "utf-8");
        const durationMs = Date.now() - startTime;

        logger.info(
          { tool: "append_file", request_id: requestId, duration_ms: durationMs, outcome: "success", appended_bytes: appendedBytes },
          "tool_call_end",
        );

        const structured = {
          success: true,
          path: resolvedPath,
          appended_bytes: appendedBytes,
        };

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: `Successfully appended to ${resolvedPath}` }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "append_file", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error appending to file: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
