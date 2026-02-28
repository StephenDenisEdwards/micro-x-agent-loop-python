import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";

export function registerWriteFile(server: McpServer, logger: Logger, workingDir: string): void {
  server.registerTool(
    "write_file",
    {
      description: "Write content to a file, creating it if it doesn't exist. Parent directories are created automatically.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute or relative path to the file to write"),
        content: z.string().describe("The content to write to the file"),
      },
      outputSchema: {
        success: z.boolean(),
        path: z.string(),
        size_bytes: z.number().int(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "write_file", request_id: requestId, path: input.path }, "tool_call_start");

      try {
        const resolvedPath = path.isAbsolute(input.path)
          ? input.path
          : path.resolve(workingDir, input.path);

        await mkdir(path.dirname(resolvedPath), { recursive: true });
        await writeFile(resolvedPath, input.content, "utf-8");

        const sizeBytes = Buffer.byteLength(input.content, "utf-8");
        const durationMs = Date.now() - startTime;

        logger.info(
          { tool: "write_file", request_id: requestId, duration_ms: durationMs, outcome: "success", size_bytes: sizeBytes },
          "tool_call_end",
        );

        const structured = {
          success: true,
          path: resolvedPath,
          size_bytes: sizeBytes,
        };

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: `Successfully wrote to ${resolvedPath}` }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "write_file", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error writing file: ${message}` }],
          isError: true,
        };
      }
    },
  );
}
