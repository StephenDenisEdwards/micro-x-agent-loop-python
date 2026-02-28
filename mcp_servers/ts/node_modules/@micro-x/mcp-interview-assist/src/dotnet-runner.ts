import { execFile, type ChildProcess } from "node:child_process";
import path from "node:path";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";

const DEFAULT_INTERVIEW_ASSIST_REPO = String.raw`C:\Users\steph\source\repos\interview-assist-2`;
const TRANSCRIPTION_CONSOLE_PROJECT =
  "Interview-assist-transcription-detection-console/Interview-assist-transcription-detection-console.csproj";
const STT_CLI_PROJECT = "Interview-assist-stt-cli/Interview-assist-stt-cli.csproj";

export { TRANSCRIPTION_CONSOLE_PROJECT, STT_CLI_PROJECT };

export function resolveRepo(repoPath?: string): string {
  const selected = (repoPath || process.env.INTERVIEW_ASSIST_REPO || DEFAULT_INTERVIEW_ASSIST_REPO).trim();
  const resolved = path.resolve(selected);

  if (!existsSync(resolved)) {
    throw new Error(`Interview Assist repo does not exist: ${resolved}`);
  }

  const project = path.join(resolved, TRANSCRIPTION_CONSOLE_PROJECT);
  if (!existsSync(project)) {
    throw new Error(`Transcription detection project not found: ${project}`);
  }

  return resolved;
}

export function dotnetRunCommand(repo: string, projectRelativePath: string, args: string[]): string[] {
  const project = path.join(repo, projectRelativePath);
  return ["dotnet", "run", "--no-build", "--project", project, "--", ...args];
}

export interface RunResult {
  command: string[];
  cwd: string;
  exit_code: number;
  stdout: string;
  stderr: string;
}

export function runDotnetProject(
  repo: string,
  projectRelativePath: string,
  args: string[],
  timeoutSeconds = 900,
): Promise<RunResult> {
  const project = path.join(repo, projectRelativePath);
  if (!existsSync(project)) {
    throw new Error(`Project not found: ${project}`);
  }

  const command = dotnetRunCommand(repo, projectRelativePath, args);

  return new Promise((resolve, reject) => {
    const child = execFile(command[0], command.slice(1), {
      cwd: repo,
      timeout: Math.max(1, timeoutSeconds) * 1000,
      maxBuffer: 50 * 1024 * 1024,
      windowsHide: true,
    }, (error, stdout, stderr) => {
      const exitCode = error && "code" in error && typeof error.code === "number"
        ? error.code
        : (child.exitCode ?? 0);

      const result: RunResult = {
        command,
        cwd: repo,
        exit_code: exitCode,
        stdout: stdout ?? "",
        stderr: stderr ?? "",
      };

      if (exitCode !== 0) {
        reject(new Error(
          `Interview Assist command failed\nexit_code: ${exitCode}\n` +
          `stdout_tail: ${result.stdout.slice(-2000)}\nstderr_tail: ${result.stderr.slice(-2000)}`,
        ));
        return;
      }

      resolve(result);
    });
  });
}

export function runInterviewAssist(repo: string, args: string[], timeoutSeconds = 900): Promise<RunResult> {
  return runDotnetProject(repo, TRANSCRIPTION_CONSOLE_PROJECT, args, timeoutSeconds);
}

export function runSttCli(repo: string, args: string[], timeoutSeconds = 120): Promise<RunResult> {
  return runDotnetProject(repo, STT_CLI_PROJECT, args, timeoutSeconds);
}

export function findOutputLineValue(output: string, prefix: string): string | null {
  const pattern = new RegExp(`^${escapeRegExp(prefix)}\\s*(.+?)\\s*$`, "m");
  const match = pattern.exec(output);
  return match ? match[1].trim() : null;
}

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export async function safeLoadJson(filePath: string): Promise<Record<string, unknown> | null> {
  if (!existsSync(filePath)) return null;
  try {
    const text = await readFile(filePath, "utf-8");
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function evaluationSummary(report: Record<string, unknown> | null): Record<string, unknown> {
  if (!report) return {};
  const metrics = (report.Metrics ?? {}) as Record<string, unknown>;
  const subtype = (report.SubtypeAccuracy ?? {}) as Record<string, unknown>;
  return {
    generated_at: report.GeneratedAt,
    session_file: report.SessionFile,
    ground_truth_source: report.GroundTruthSource,
    metrics: {
      true_positives: metrics.TruePositives,
      false_positives: metrics.FalsePositives,
      false_negatives: metrics.FalseNegatives,
      precision: metrics.Precision,
      recall: metrics.Recall,
      f1_score: metrics.F1Score,
    },
    subtype_accuracy: {
      overall_accuracy: subtype.OverallAccuracy,
      total_with_subtype: subtype.TotalWithSubtype,
      total_correct: subtype.TotalCorrect,
    },
    counts: {
      matches: ((report.Matches ?? []) as unknown[]).length,
      missed: ((report.Missed ?? []) as unknown[]).length,
      false_alarms: ((report.FalseAlarms ?? []) as unknown[]).length,
    },
  };
}

export function spawnDotnetStream(repo: string, projectRelativePath: string, args: string[]): ChildProcess {
  const { spawn } = require("node:child_process") as typeof import("node:child_process");
  const command = dotnetRunCommand(repo, projectRelativePath, args);
  return spawn(command[0], command.slice(1), {
    cwd: repo,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
}
