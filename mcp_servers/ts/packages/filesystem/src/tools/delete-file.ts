import { unlink, stat } from "node:fs/promises";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { resolveAllowed, requireWritable, type PathPolicy } from "../paths.js";

export function registerDeleteFile(server: McpServer, logger: Logger, policy: PathPolicy): void {
  server.registerTool(
    "delete_file",
    {
      description:
        "Delete a single file. " +
        "Refuses directories — use bash for recursive or bulk deletion (rm -r, rmdir). " +
        "Path must be inside FILESYSTEM_WORKING_DIR or FILESYSTEM_ALLOWED_DIRS — absolute paths outside the allowed roots are rejected. " +
        "The file is checkpointed before deletion so /rewind can restore it. " +
        "Use this — not bash rm — for single-file deletes: cross-platform, path-contained, recoverable.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute or relative path to the file to delete"),
      },
      outputSchema: {
        path: z.string(),
        deleted: z.boolean(),
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

      logger.info(
        { tool: "delete_file", request_id: requestId, path: input.path },
        "tool_call_start",
      );

      try {
        const resolvedPath = await resolveAllowed(policy, input.path, { mustExist: false });
        await requireWritable(policy, resolvedPath);

        let st;
        try {
          st = await stat(resolvedPath);
        } catch {
          return errorResult(`file not found: ${resolvedPath}`);
        }
        if (st.isDirectory()) {
          return errorResult(
            `refusing to delete directory: ${resolvedPath} — use bash (rm -r / rmdir) for directory removal`,
          );
        }
        if (!st.isFile()) {
          return errorResult(`not a regular file: ${resolvedPath}`);
        }

        await unlink(resolvedPath);

        const durationMs = Date.now() - startTime;
        logger.info(
          {
            tool: "delete_file",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "success",
            size_bytes: st.size,
          },
          "tool_call_end",
        );

        return {
          structuredContent: { path: resolvedPath, deleted: true, size_bytes: st.size },
          content: [{ type: "text" as const, text: `deleted ${resolvedPath} (${st.size} bytes)` }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);
        logger.error(
          {
            tool: "delete_file",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "error",
            error_message: message,
          },
          "tool_call_end",
        );
        return errorResult(`Error deleting file: ${message}`);
      }
    },
  );
}

function errorResult(text: string) {
  return { content: [{ type: "text" as const, text }], isError: true };
}
