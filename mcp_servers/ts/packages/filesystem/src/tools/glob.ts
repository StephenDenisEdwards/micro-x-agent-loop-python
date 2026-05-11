import { stat } from "node:fs/promises";
import { z } from "zod";
import fg from "fast-glob";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { resolveAllowed, type PathPolicy } from "../paths.js";

const DEFAULT_HEAD_LIMIT = 250;

export function registerGlob(server: McpServer, logger: Logger, policy: PathPolicy): void {
  server.registerTool(
    "glob",
    {
      description:
        'Find files by name pattern using fast-glob (e.g. "**/*.ts", "src/**/*.{js,jsx}", "tests/**/test_*.py"). ' +
        "Returns absolute paths sorted by mtime (newest first). Searches the workspace working dir plus any FILESYSTEM_ALLOWED_DIRS roots. " +
        "USE THIS — not bash find / ls -R — to discover files. It is cross-platform, structured (clean list of absolute paths), and path-contained. " +
        "For content search use grep. For reading a file you already know the path of use read_file.",
      inputSchema: {
        pattern: z.string().min(1).describe("Glob pattern (fast-glob/micromatch syntax)"),
        path: z.string().optional().describe("Root to search from. Defaults to working dir."),
        head_limit: z.number().int().min(1).max(5000).default(DEFAULT_HEAD_LIMIT),
      },
      outputSchema: {
        paths: z.array(z.string()),
        total: z.number().int(),
        truncated: z.boolean(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      logger.info(
        { tool: "glob", request_id: requestId, pattern: input.pattern },
        "tool_call_start",
      );

      try {
        const root = await resolveAllowed(policy, input.path, { mustExist: true });

        const matches = await fg(input.pattern, {
          cwd: root,
          absolute: true,
          dot: false,
          onlyFiles: true,
          followSymbolicLinks: false,
          suppressErrors: true,
        });

        const withStats = await Promise.all(
          matches.map(async (p) => ({
            p,
            mtime: (await stat(p).catch(() => null))?.mtimeMs ?? 0,
          })),
        );
        withStats.sort((a, b) => b.mtime - a.mtime);
        const sorted = withStats.map(({ p }) => p);

        const truncated = sorted.length > input.head_limit;
        const kept = truncated ? sorted.slice(0, input.head_limit) : sorted;

        logger.info(
          {
            tool: "glob",
            request_id: requestId,
            duration_ms: Date.now() - startTime,
            outcome: "success",
            total: sorted.length,
            truncated,
          },
          "tool_call_end",
        );

        let text: string;
        if (!kept.length) {
          text = "(no matches)";
        } else if (truncated) {
          const pct = Math.max(1, Math.round((input.head_limit / sorted.length) * 100));
          const bumpedLimit = Math.min(5000, sorted.length);
          const escapedPattern = input.pattern.replace(/"/g, '\\"');
          const pathArg = input.path ? `, path="${input.path}"` : "";
          text =
            kept.join("\n") +
            `\n\n[Output truncated: showed first ${input.head_limit} of ${sorted.length} paths (${pct}%).\n` +
            ` To see more: glob(pattern="${escapedPattern}"${pathArg}, head_limit=${bumpedLimit}) — or narrow the pattern]`;
        } else {
          text = kept.join("\n");
        }

        return {
          structuredContent: { paths: kept, total: sorted.length, truncated },
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error(
          {
            tool: "glob",
            request_id: requestId,
            duration_ms: Date.now() - startTime,
            outcome: "error",
            error_message: message,
          },
          "tool_call_end",
        );
        return { content: [{ type: "text" as const, text: `glob error: ${message}` }], isError: true };
      }
    },
  );
}
