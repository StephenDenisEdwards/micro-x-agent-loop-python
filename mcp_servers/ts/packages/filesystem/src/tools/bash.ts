import { execFile } from "node:child_process";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { isPathAllowed, type PathPolicy } from "../paths.js";

const IS_WINDOWS = process.platform === "win32";
const TIMEOUT_MS = 30_000;
const MAX_BUFFER = 10 * 1024 * 1024;

const WIN_DRIVE_RE = /^[A-Za-z]:[\\/]/;
const UNC_PREFIX = "\\\\";

interface AllowlistConfig {
  mode: "unset" | "deny_all" | "list";
  set: Set<string>;
}

export function registerBash(
  server: McpServer,
  logger: Logger,
  workingDir: string,
  policy: PathPolicy,
): void {
  const pathGuardEnabled = parseEnvBool("FILESYSTEM_BASH_PATH_GUARD", true);
  const allowlist = readAllowlist("FILESYSTEM_BASH_ALLOWED_COMMANDS");

  logger.info(
    {
      bash_path_guard: pathGuardEnabled,
      bash_allowlist_mode: allowlist.mode,
      bash_allowlist_size: allowlist.set.size,
    },
    "bash_containment_config",
  );

  server.registerTool(
    "bash",
    {
      description:
        "Execute a shell command in the workspace working directory. Returns combined stdout + stderr, exit code, and a timed_out flag. " +
        "USE FOR: running tests (pytest, npm test), git commands, build tools (npm run build, cargo build), package managers (npm install, pip install), and anything no dedicated tool covers. " +
        "DO NOT USE for filesystem work — there are dedicated tools that are cross-platform, structured, and path-contained: " +
        "cat / head / tail → use read_file (line-numbered, offset/limit). " +
        "grep / rg → use grep (ripgrep, three output modes). " +
        "find / ls -R → use glob (mtime-sorted). " +
        "sed / awk for edits → use edit_file (exact-string, atomic). " +
        "echo > file → use write_file. " +
        "echo >> file → use append_file. " +
        "rm <file> → use delete_file (checkpointed — /rewind restores). bash rm is for directories (rm -r / rmdir) and bulk deletion only. " +
        "Cross-platform pitfall: the shell is cmd.exe on Windows and /bin/sh elsewhere — quoting, chain operators (`;` vs `&`), and path conventions differ. The dedicated FS tools sidestep this. " +
        "Containment (ACCIDENT PREVENTION only — NOT adversarial sandboxing). " +
        "FILESYSTEM_BASH_PATH_GUARD (default ON, set =false to disable) rejects commands that reference absolute paths or `..` traversal resolving outside FILESYSTEM_WORKING_DIR / FILESYSTEM_ALLOWED_DIRS. " +
        "FILESYSTEM_BASH_ALLOWED_COMMANDS (opt-in, comma-separated) restricts execution to commands whose FIRST token is in the list — pipes, chains, subshells, and command substitution are NOT decomposed. Set to empty string for a kill switch. " +
        "These are string-level filters and trivially bypassable by a determined or prompt-injected agent (sh -c, env-var indirection, base64 pipelines, write-then-execute). Real isolation requires OS-level controls.",
      inputSchema: {
        command: z.string().describe("The shell command to execute"),
      },
      outputSchema: {
        stdout: z.string(),
        stderr: z.string(),
        exit_code: z.number().int(),
        timed_out: z.boolean(),
        output_truncated: z.boolean(),
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
        { tool: "bash", request_id: requestId, command: input.command.slice(0, 200) },
        "tool_call_start",
      );

      // 1. Allowlist
      if (allowlist.mode === "deny_all") {
        return refusal(
          logger,
          requestId,
          startTime,
          "deny_all",
          "bash is disabled (FILESYSTEM_BASH_ALLOWED_COMMANDS is set to empty — kill switch). Unset the env var or list permitted first-tokens to re-enable.",
        );
      }
      if (allowlist.mode === "list") {
        const firstToken = extractFirstToken(input.command);
        if (firstToken === undefined) {
          return refusal(logger, requestId, startTime, "empty_command", "bash: command is empty");
        }
        if (!allowlist.set.has(firstToken)) {
          const allowed = [...allowlist.set].sort().join(", ");
          return refusal(
            logger,
            requestId,
            startTime,
            "allowlist_miss",
            `bash: command "${firstToken}" is not in FILESYSTEM_BASH_ALLOWED_COMMANDS allowlist (allowed: ${allowed}). ` +
              "Note: only the first token is checked — pipes / chains / subshells / command substitution are not decomposed.",
          );
        }
      }

      // 2. Path guard
      if (pathGuardEnabled) {
        const violation = await checkPathGuard(input.command, policy);
        if (violation !== null) {
          return refusal(logger, requestId, startTime, "path_guard", violation);
        }
      }

      // 3. Execute
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
            output_truncated: result.output_truncated,
            outcome:
              result.exit_code === 0 && !result.timed_out && !result.output_truncated
                ? "success"
                : "error",
          },
          "tool_call_end",
        );

        const textParts: string[] = [];
        const combined = result.stdout + result.stderr;
        if (combined) textParts.push(combined.trimEnd());
        if (result.timed_out) {
          textParts.push(`[timed out after ${TIMEOUT_MS / 1000}s]`);
        } else if (result.output_truncated) {
          const cap = formatBytes(MAX_BUFFER);
          textParts.push(
            `[Output truncated: command emitted >${cap} to stdout+stderr; ` +
              `output cut at the ${cap} boundary and the process was killed.\n` +
              ` To capture more: redirect to a file (e.g., \`command > /tmp/out.log 2>&1\`) and ` +
              `use read_file with offset/limit, or narrow via head/tail/grep in the command itself]`,
          );
        } else if (result.exit_code !== 0) {
          textParts.push(`[exit code ${result.exit_code}]`);
        }

        return {
          structuredContent: { ...result },
          content: [{ type: "text" as const, text: textParts.join("\n") || "(no output)" }],
          isError: result.exit_code !== 0 || result.timed_out || result.output_truncated,
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          {
            tool: "bash",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "error",
            error_message: message,
          },
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

function refusal(
  logger: Logger,
  requestId: string,
  startTime: number,
  reason: string,
  text: string,
) {
  logger.warn(
    {
      tool: "bash",
      request_id: requestId,
      duration_ms: Date.now() - startTime,
      outcome: "refused",
      refused_reason: reason,
    },
    "tool_call_end",
  );
  return { content: [{ type: "text" as const, text }], isError: true };
}

function extractFirstToken(command: string): string | undefined {
  const match = command.trim().match(/^\S+/);
  return match ? match[0] : undefined;
}

function parseEnvBool(name: string, fallback: boolean): boolean {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const v = raw.trim().toLowerCase();
  if (v === "0" || v === "false" || v === "no" || v === "off") return false;
  if (v === "1" || v === "true" || v === "yes" || v === "on") return true;
  return fallback;
}

function readAllowlist(name: string): AllowlistConfig {
  const raw = process.env[name];
  if (raw === undefined) return { mode: "unset", set: new Set() };
  const trimmed = raw.trim();
  if (trimmed === "") return { mode: "deny_all", set: new Set() };
  const items = trimmed
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  return { mode: "list", set: new Set(items) };
}

// Path-guard helpers
//
// Tokenisation is deliberately simple — whitespace + `=` split, with quote
// chars stripped to expose paths inside them. This is accident prevention,
// not adversarial sandboxing: pipes / chains / subshells / command
// substitution are not decomposed, and the tool description says so. A
// determined or prompt-injected agent can defeat this trivially.

function findPathCandidates(command: string): string[] {
  const candidates: string[] = [];
  const cleaned = command.replace(/['"]/g, " ");
  const tokens = cleaned.split(/[\s=]+/).filter((t) => t.length > 0);

  for (const raw of tokens) {
    const token = raw.replace(/^[;&|()<>{}]+/, "").replace(/[;&|()<>{}]+$/, "");
    if (token.length === 0) continue;

    if (looksLikeAbsolutePath(token) || looksLikeTraversal(token)) {
      candidates.push(token);
    }
  }

  return candidates;
}

function looksLikeAbsolutePath(token: string): boolean {
  if (IS_WINDOWS) {
    // Windows: drive-letter (C:\..., C:/...) or UNC (\\server\share)
    return WIN_DRIVE_RE.test(token) || token.startsWith(UNC_PREFIX);
  }
  // POSIX: leading slash. Excludes a bare "/" since that's not a useful path.
  return token.startsWith("/") && token.length > 1;
}

function looksLikeTraversal(token: string): boolean {
  // Has ".." as a path component (not just inside another word).
  const normalised = token.replace(/\\/g, "/");
  if (normalised === "..") return true;
  if (normalised.startsWith("../")) return true;
  if (normalised.includes("/../")) return true;
  if (normalised.endsWith("/..")) return true;
  return false;
}

async function checkPathGuard(command: string, policy: PathPolicy): Promise<string | null> {
  const candidates = findPathCandidates(command);
  if (candidates.length === 0) return null;

  for (const cand of candidates) {
    const allowed = await isPathAllowed(policy, cand);
    if (!allowed) {
      const rootList = [policy.workingDir, ...policy.extraAllowed].join(IS_WINDOWS ? "; " : ":");
      return (
        `bash: refusing to execute — command references path "${cand}" outside the allowed roots. ` +
        `Allowed: ${rootList}. ` +
        "Set FILESYSTEM_BASH_PATH_GUARD=false to disable, or add the root to FILESYSTEM_ALLOWED_DIRS. " +
        "(Accident prevention only — not adversarial sandboxing; see ISSUE-005.)"
      );
    }
  }

  return null;
}

interface BashResult {
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
  output_truncated: boolean;
}

function runCommand(command: string, cwd: string): Promise<BashResult> {
  return new Promise((resolve) => {
    const shell = IS_WINDOWS ? "cmd.exe" : "/bin/sh";
    const shellArgs = IS_WINDOWS ? ["/c", command] : ["-c", command];

    const child = execFile(
      shell,
      shellArgs,
      {
        cwd,
        timeout: TIMEOUT_MS,
        maxBuffer: MAX_BUFFER,
        windowsHide: true,
      },
      (error, stdout, stderr) => {
        // maxBuffer overflow also sets error.killed, so detect it FIRST and
        // distinguish from a real timeout-kill.
        const outputTruncated =
          !!error
          && "code" in error
          && error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER_EXCEEDED";

        if (outputTruncated) {
          resolve({
            stdout: stdout ?? "",
            stderr: stderr ?? "",
            exit_code: -1,
            timed_out: false,
            output_truncated: true,
          });
          return;
        }

        if (error && "killed" in error && error.killed) {
          resolve({
            stdout: stdout ?? "",
            stderr: stderr ?? "",
            exit_code: -1,
            timed_out: true,
            output_truncated: false,
          });
          return;
        }

        const exitCode =
          error && "code" in error && typeof error.code === "number"
            ? error.code
            : (child.exitCode ?? 0);

        resolve({
          stdout: stdout ?? "",
          stderr: stderr ?? "",
          exit_code: exitCode,
          timed_out: false,
          output_truncated: false,
        });
      },
    );
  });
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}KB`;
  return `${(n / (1024 * 1024)).toFixed(1)}MB`;
}
