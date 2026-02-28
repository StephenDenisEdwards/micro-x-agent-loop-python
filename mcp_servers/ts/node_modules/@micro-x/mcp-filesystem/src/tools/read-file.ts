import { readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";

export function registerReadFile(server: McpServer, logger: Logger, workingDir: string): void {
  server.registerTool(
    "read_file",
    {
      description:
        "Read the contents of a file and return it as text. Supports plain text files and .docx documents.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute or relative path to the file to read"),
      },
      outputSchema: {
        content: z.string(),
        path: z.string(),
        size_bytes: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "read_file", request_id: requestId, path: input.path }, "tool_call_start");

      try {
        const resolvedPath = path.isAbsolute(input.path)
          ? input.path
          : path.resolve(workingDir, input.path);

        let content: string;

        if (resolvedPath.toLowerCase().endsWith(".docx")) {
          content = await readDocx(resolvedPath);
        } else {
          content = await readFile(resolvedPath, "utf-8");
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "read_file", request_id: requestId, duration_ms: durationMs, outcome: "success", size_bytes: Buffer.byteLength(content) },
          "tool_call_end",
        );

        const structured = {
          content,
          path: resolvedPath,
          size_bytes: Buffer.byteLength(content),
        };

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: content }],
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

async function readDocx(filePath: string): Promise<string> {
  const mammoth = await import("mammoth");
  const result = await mammoth.default.extractRawText({ path: filePath });
  return result.value;
}
