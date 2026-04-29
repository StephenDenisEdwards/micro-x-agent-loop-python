import { execFile } from "node:child_process";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";

const IS_WINDOWS = process.platform === "win32";
const TIMEOUT_MS = 30_000;

export function registerBash(server: McpServer, logger: Logger, workingDir: string): void {
  server.registerTool(
    "bash",
    {
      description: "Execute a shell command and return its output (stdout + stderr).",
      inputSchema: {
        command: z.string().describe("The shell command to execute"),
      },
      outputSchema: {
        stdout: z.string(),
        stderr: z.string(),
        exit_code: z.number().int(),
        timed_out: z.boolean(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "bash", request_id: requestId, command: input.command.slice(0, 200) }, "tool_call_start");

      try {
        const result = await runCommand(input.command, workingDir);
        const durationMs = Date.now() - startTime;

        logger.info(
          {
            tool: "bash",
            request_id: requestId,
            duration_ms: durationMs,
            exit_code: result.exit_code,
            timed_out: result.timed_out,
            outcome: result.exit_code === 0 && !result.timed_out ? "success" : "error",
          },
          "tool_call_end",
        );

        const textParts: string[] = [];
        const combined = result.stdout + result.stderr;
        if (combined) textParts.push(combined.trimEnd());
        if (result.timed_out) textParts.push(`[timed out after ${TIMEOUT_MS / 1000}s]`);
        else if (result.exit_code !== 0) textParts.push(`[exit code ${result.exit_code}]`);

        return {
          structuredContent: { ...result },
          content: [{ type: "text" as const, text: textParts.join("\n") || "(no output)" }],
          isError: result.exit_code !== 0 || result.timed_out,
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "bash", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error executing command: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

interface BashResult {
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
}

function runCommand(command: string, cwd: string): Promise<BashResult> {
  return new Promise((resolve) => {
    const shell = IS_WINDOWS ? "cmd.exe" : "/bin/sh";
    const shellArgs = IS_WINDOWS ? ["/c", command] : ["-c", command];

    const child = execFile(shell, shellArgs, {
      cwd,
      timeout: TIMEOUT_MS,
      maxBuffer: 10 * 1024 * 1024, // 10 MB
      windowsHide: true,
    }, (error, stdout, stderr) => {
      if (error && "killed" in error && error.killed) {
        resolve({ stdout: stdout ?? "", stderr: stderr ?? "", exit_code: -1, timed_out: true });
        return;
      }

      const exitCode = error && "code" in error && typeof error.code === "number"
        ? error.code
        : (child.exitCode ?? 0);

      resolve({
        stdout: stdout ?? "",
        stderr: stderr ?? "",
        exit_code: exitCode,
        timed_out: false,
      });
    });
  });
}
