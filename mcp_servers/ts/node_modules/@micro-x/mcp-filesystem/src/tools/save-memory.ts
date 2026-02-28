import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { PermissionError, ValidationError } from "@micro-x/mcp-shared";

export function registerSaveMemory(server: McpServer, logger: Logger, memoryDir: string, maxLines: number): void {
  server.registerTool(
    "save_memory",
    {
      description:
        `Save persistent memory that will be loaded in future sessions. ` +
        `Files are stored in the user memory directory. ` +
        `Use MEMORY.md as the main index (first ${maxLines} lines loaded automatically). ` +
        `Create topic files for detailed notes and reference them from MEMORY.md.`,
      inputSchema: {
        file: z
          .string()
          .min(1)
          .describe("Filename within the memory directory (e.g. 'MEMORY.md', 'patterns.md'). Must end with .md."),
        content: z.string().describe("Full file content to write."),
      },
      outputSchema: {
        success: z.boolean(),
        file: z.string(),
        message: z.string(),
        line_count: z.number().int().optional(),
        warning: z.string().optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "save_memory", request_id: requestId, file: input.file }, "tool_call_start");

      try {
        // Validate .md extension
        if (!input.file.endsWith(".md")) {
          throw new ValidationError("Only .md files are allowed in the memory directory.");
        }

        // Prevent path traversal
        if (input.file.includes("/") || input.file.includes("\\") || input.file.includes("..")) {
          throw new PermissionError("'file' must be a plain filename (no path separators or '..').");
        }

        const targetPath = path.join(memoryDir, input.file);

        await mkdir(memoryDir, { recursive: true });
        await writeFile(targetPath, input.content, "utf-8");

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "save_memory", request_id: requestId, duration_ms: durationMs, outcome: "success", file: input.file },
          "tool_call_end",
        );

        let message = `Successfully saved ${input.file}`;
        let warning: string | undefined;
        let lineCount: number | undefined;

        // Line-count warning for MEMORY.md
        if (input.file === "MEMORY.md") {
          lineCount = input.content.split("\n").length;
          if (!input.content.endsWith("\n") && input.content.length > 0) {
            // count correctly — same logic as Python version
          } else if (input.content.endsWith("\n")) {
            lineCount--;
          }

          if (lineCount > maxLines) {
            warning =
              `MEMORY.md is ${lineCount} lines but only the first ${maxLines} lines are loaded into context. ` +
              `Consider moving detailed content to topic files and linking from MEMORY.md.`;
            message += `\n\nWarning: ${warning}`;
          }
        }

        const structured: Record<string, unknown> = {
          success: true,
          file: input.file,
          message: `Successfully saved ${input.file}`,
        };
        if (lineCount !== undefined) structured.line_count = lineCount;
        if (warning !== undefined) structured.warning = warning;

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text: message }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);
        const isValidation = err instanceof ValidationError || err instanceof PermissionError;

        logger.error(
          {
            tool: "save_memory",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "error",
            error_code: isValidation ? "validation_error" : "internal_error",
            error_message: message,
          },
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
