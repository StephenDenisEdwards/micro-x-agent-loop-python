import { execFile } from "node:child_process";
import { z } from "zod";
import { rgPath } from "@vscode/ripgrep";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { resolveAllowed, type PathPolicy } from "../paths.js";

const TIMEOUT_MS = 30_000;
const MAX_BUFFER = 10 * 1024 * 1024;
const DEFAULT_HEAD_LIMIT = 250;

const OutputMode = z.enum(["content", "files_with_matches", "count"]);

export function registerGrep(server: McpServer, logger: Logger, policy: PathPolicy): void {
  server.registerTool(
    "grep",
    {
      description:
        "Search file contents using ripgrep. Supports regex, glob/type filters, and three output modes. " +
        "Respects .gitignore by default. Prefer this over `bash grep` — it is cross-platform and structured.",
      inputSchema: {
        pattern: z.string().min(1).describe("Regex pattern (ripgrep/Rust regex syntax)"),
        path: z.string().optional().describe("File or directory to search. Defaults to working dir."),
        glob: z.string().optional().describe('Glob filter, e.g. "*.ts" or "src/**/*.py"'),
        type: z.string().optional().describe('File type filter, e.g. "ts", "py", "rust"'),
        output_mode: OutputMode.default("files_with_matches"),
        case_insensitive: z.boolean().default(false),
        line_numbers: z.boolean().default(true).describe("Show line numbers (content mode only)"),
        context: z.number().int().min(0).max(20).optional().describe("Lines of context before/after each match"),
        multiline: z.boolean().default(false).describe("Allow patterns to span lines (. matches \\n)"),
        head_limit: z.number().int().min(1).max(5000).default(DEFAULT_HEAD_LIMIT),
      },
      outputSchema: {
        mode: OutputMode,
        results: z.string(),
        match_count: z.number().int(),
        truncated: z.boolean(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      logger.info(
        { tool: "grep", request_id: requestId, pattern: input.pattern.slice(0, 200), mode: input.output_mode },
        "tool_call_start",
      );

      try {
        const searchPath = await resolveAllowed(policy, input.path, { mustExist: true });
        const args = buildArgs(input, searchPath);
        const { stdout, exitCode } = await runRg(args);
        if (exitCode === 2) throw new Error(stdout || "ripgrep error");

        const lines = stdout.length ? stdout.split("\n").filter(Boolean) : [];
        const totalCount = input.output_mode === "count" ? sumCounts(lines) : lines.length;
        const truncated = lines.length > input.head_limit;
        const kept = truncated ? lines.slice(0, input.head_limit) : lines;
        const results = kept.join("\n");

        logger.info(
          {
            tool: "grep",
            request_id: requestId,
            duration_ms: Date.now() - startTime,
            outcome: "success",
            match_count: totalCount,
            truncated,
          },
          "tool_call_end",
        );

        const text = !results
          ? "(no matches)"
          : results
            + (truncated
              ? `\n\n[truncated to ${input.head_limit} of ${lines.length} lines — narrow with glob/type or raise head_limit]`
              : "");

        return {
          structuredContent: { mode: input.output_mode, results, match_count: totalCount, truncated },
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error(
          {
            tool: "grep",
            request_id: requestId,
            duration_ms: Date.now() - startTime,
            outcome: "error",
            error_message: message,
          },
          "tool_call_end",
        );
        return { content: [{ type: "text" as const, text: `grep error: ${message}` }], isError: true };
      }
    },
  );
}

interface GrepInput {
  pattern: string;
  path?: string;
  glob?: string;
  type?: string;
  output_mode: "content" | "files_with_matches" | "count";
  case_insensitive: boolean;
  line_numbers: boolean;
  context?: number;
  multiline: boolean;
  head_limit: number;
}

function buildArgs(input: GrepInput, searchPath: string): string[] {
  const args: string[] = [];

  switch (input.output_mode) {
    case "files_with_matches":
      args.push("--files-with-matches");
      break;
    case "count":
      args.push("--count-matches");
      break;
    case "content":
      if (input.line_numbers) args.push("--line-number");
      if (input.context !== undefined) args.push(`--context=${input.context}`);
      break;
  }

  if (input.case_insensitive) args.push("--ignore-case");
  if (input.multiline) args.push("--multiline", "--multiline-dotall");
  if (input.glob) args.push("--glob", input.glob);
  if (input.type) args.push("--type", input.type);

  args.push("--", input.pattern, searchPath);
  return args;
}

function sumCounts(lines: string[]): number {
  let total = 0;
  for (const line of lines) {
    const tail = line.split(":").pop();
    const n = tail ? parseInt(tail, 10) : 0;
    if (!Number.isNaN(n)) total += n;
  }
  return total;
}

function runRg(args: string[]): Promise<{ stdout: string; exitCode: number }> {
  return new Promise((resolve, reject) => {
    execFile(
      rgPath,
      args,
      { timeout: TIMEOUT_MS, maxBuffer: MAX_BUFFER, windowsHide: true },
      (error, stdout, stderr) => {
        const exitCode =
          error && "code" in error && typeof error.code === "number" ? error.code : 0;
        if (error && exitCode !== 1) {
          if ("killed" in error && error.killed) {
            return reject(new Error(`timed out after ${TIMEOUT_MS / 1000}s`));
          }
          return reject(new Error(stderr || error.message));
        }
        resolve({ stdout, exitCode });
      },
    );
  });
}
