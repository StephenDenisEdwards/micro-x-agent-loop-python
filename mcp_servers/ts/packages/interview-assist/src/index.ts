#!/usr/bin/env node

import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { existsSync } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import { z } from "zod";
import { createLogger, createServer, startStdioServer } from "@micro-x-ai/mcp-shared";
import {
  resolveRepo,
  runInterviewAssist,
  runSttCli,
  findOutputLineValue,
  safeLoadJson,
  evaluationSummary,
  dotnetRunCommand,
  STT_CLI_PROJECT,
} from "./dotnet-runner.js";
import {
  createSession,
  getSession,
  pushEvent,
  utcNow,
  type SttSession,
} from "./stt-session.js";

const logger = createLogger("mcp-interview-assist");

const server = createServer({
  name: "interview-assist",
  version: "0.1.0",
  logger,
});

function tempJsonPath(prefix: string): string {
  return path.join(tmpdir(), `${prefix}-${crypto.randomUUID()}.json`);
}

function jsonResult(data: Record<string, unknown>): { content: Array<{ type: "text"; text: string }>; structuredContent: Record<string, unknown> } {
  return {
    structuredContent: data,
    content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
  };
}

function errorResult(message: string): { content: Array<{ type: "text"; text: string }>; isError: true } {
  return { content: [{ type: "text" as const, text: message }], isError: true as const };
}

// --- ia_healthcheck ---
server.registerTool("ia_healthcheck", {
  description: "Validate Interview Assist MCP prerequisites and return detected paths.",
  inputSchema: {
    repo_path: z.string().describe("Path to interview-assist-2 repo").optional(),
  },
  annotations: { readOnlyHint: true, destructiveHint: false },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const sttProject = path.join(repo, STT_CLI_PROJECT);
    return jsonResult({
      repo_path: repo,
      project_path: path.join(repo, "Interview-assist-transcription-detection-console/Interview-assist-transcription-detection-console.csproj"),
      stt_project_path: sttProject,
      stt_project_exists: existsSync(sttProject),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_list_recordings ---
server.registerTool("ia_list_recordings", {
  description: "List recording JSONL files in interview-assist-2 recordings folder.",
  inputSchema: {
    repo_path: z.string().optional(),
    limit: z.number().int().min(1).default(30).optional(),
  },
  annotations: { readOnlyHint: true, destructiveHint: false },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const recordingsDir = path.join(repo, "recordings");
    if (!existsSync(recordingsDir)) {
      return jsonResult({ recordings_dir: recordingsDir, files: [] });
    }
    const entries = await readdir(recordingsDir);
    const jsonlFiles = entries.filter((f) => f.endsWith(".jsonl"));

    const fileInfos = await Promise.all(
      jsonlFiles.map(async (f) => {
        const filePath = path.join(recordingsDir, f);
        const s = await stat(filePath);
        return { path: filePath, name: f, size_bytes: s.size, mtime: s.mtimeMs };
      }),
    );
    fileInfos.sort((a, b) => b.mtime - a.mtime);
    const selected = fileInfos.slice(0, input.limit ?? 30).map(({ mtime: _m, ...rest }) => rest);
    return jsonResult({ recordings_dir: recordingsDir, files: selected });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_analyze_session ---
server.registerTool("ia_analyze_session", {
  description: "Generate markdown report for a session JSONL using interview-assist-2 analyze mode.",
  inputSchema: {
    session_file: z.string().min(1),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(900).optional(),
  },
  annotations: { readOnlyHint: true, destructiveHint: false },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const result = await runInterviewAssist(repo, ["--analyze", input.session_file], input.timeout_seconds ?? 900);
    const reportPath = findOutputLineValue(result.stdout, "Report:");
    return jsonResult({
      report_path: reportPath,
      exit_code: result.exit_code,
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_evaluate_session ---
server.registerTool("ia_evaluate_session", {
  description: "Run evaluation on a session JSONL and return key precision/recall/F1 metrics.",
  inputSchema: {
    session_file: z.string().min(1),
    output_file: z.string().optional(),
    model: z.string().optional(),
    ground_truth_file: z.string().optional(),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(1800).optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const outputPath = input.output_file ? path.resolve(input.output_file) : tempJsonPath("ia-eval");
    const args = ["--evaluate", input.session_file, "--output", outputPath];
    if (input.model) args.push("--model", input.model);
    if (input.ground_truth_file) args.push("--ground-truth", input.ground_truth_file);
    const result = await runInterviewAssist(repo, args, input.timeout_seconds ?? 1800);
    const report = await safeLoadJson(outputPath);
    return jsonResult({
      output_file: outputPath,
      summary: evaluationSummary(report),
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_compare_strategies ---
server.registerTool("ia_compare_strategies", {
  description: "Compare heuristic/LLM/parallel detection strategies for a session JSONL.",
  inputSchema: {
    session_file: z.string().min(1),
    output_file: z.string().optional(),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(1800).optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const outputPath = input.output_file ? path.resolve(input.output_file) : tempJsonPath("ia-compare");
    const args = ["--compare", input.session_file, "--output", outputPath];
    const result = await runInterviewAssist(repo, args, input.timeout_seconds ?? 1800);
    const compareJson = await safeLoadJson(outputPath);
    return jsonResult({
      output_file: outputPath,
      comparison: compareJson,
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_tune_threshold ---
server.registerTool("ia_tune_threshold", {
  description: "Tune detection confidence threshold using optimize target f1/precision/recall/balanced.",
  inputSchema: {
    session_file: z.string().min(1),
    optimize: z.enum(["f1", "precision", "recall", "balanced"]).default("f1").optional(),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(1800).optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const optimize = input.optimize ?? "f1";
    const args = ["--tune-threshold", input.session_file, "--optimize", optimize];
    const result = await runInterviewAssist(repo, args, input.timeout_seconds ?? 1800);
    return jsonResult({
      optimize,
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_regression_test ---
server.registerTool("ia_regression_test", {
  description: "Run regression test for a session against a baseline file.",
  inputSchema: {
    baseline_file: z.string().min(1),
    data_file: z.string().min(1),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(1800).optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const args = ["--regression", input.baseline_file, "--data", input.data_file];
    const result = await runInterviewAssist(repo, args, input.timeout_seconds ?? 1800);
    return jsonResult({
      baseline_file: input.baseline_file,
      data_file: input.data_file,
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_create_baseline ---
server.registerTool("ia_create_baseline", {
  description: "Create baseline JSON from a session JSONL file.",
  inputSchema: {
    data_file: z.string().min(1),
    output_file: z.string().min(1),
    version: z.string().default("1.0").optional(),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(1800).optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const outputPath = path.resolve(input.output_file);
    const args = ["--create-baseline", outputPath, "--data", input.data_file, "--version", input.version ?? "1.0"];
    const result = await runInterviewAssist(repo, args, input.timeout_seconds ?? 1800);
    const baseline = await safeLoadJson(outputPath);
    return jsonResult({
      output_file: outputPath,
      baseline,
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- ia_transcribe_once ---
server.registerTool("ia_transcribe_once", {
  description: "Capture live microphone or loopback audio once and transcribe via Deepgram.",
  inputSchema: {
    duration_seconds: z.number().int().min(1).default(8).optional(),
    source: z.enum(["microphone", "loopback"]).default("microphone").optional(),
    mic_device_id: z.string().optional(),
    mic_device_name: z.string().optional(),
    sample_rate: z.number().int().min(8000).default(16000).optional(),
    model: z.string().default("nova-2").optional(),
    language: z.string().default("en").optional(),
    endpointing_ms: z.number().int().min(0).default(300).optional(),
    utterance_end_ms: z.number().int().min(0).default(1000).optional(),
    diarize: z.boolean().default(false).optional(),
    output_file: z.string().optional(),
    repo_path: z.string().optional(),
    timeout_seconds: z.number().int().min(1).default(180).optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const source = input.source ?? "microphone";
    const args = [
      "--duration-seconds", String(Math.max(1, input.duration_seconds ?? 8)),
      "--source", source,
      ...(source === "microphone" && input.mic_device_id ? ["--mic-device-id", input.mic_device_id] : []),
      ...(source === "microphone" && input.mic_device_name ? ["--mic-device-name", input.mic_device_name] : []),
      "--sample-rate", String(Math.max(8000, input.sample_rate ?? 16000)),
      "--model", input.model ?? "nova-2",
      "--language", input.language ?? "en",
      "--endpointing-ms", String(Math.max(0, input.endpointing_ms ?? 300)),
      "--utterance-end-ms", String(Math.max(0, input.utterance_end_ms ?? 1000)),
      "--diarize", input.diarize ? "true" : "false",
    ];
    let outputPath: string | null = null;
    if (input.output_file) {
      outputPath = path.resolve(input.output_file);
      args.push("--output", outputPath);
    }
    const result = await runSttCli(repo, args, input.timeout_seconds ?? 180);
    let payload = outputPath ? await safeLoadJson(outputPath) : null;
    if (!payload) {
      try { payload = JSON.parse(result.stdout) as Record<string, unknown>; } catch { payload = null; }
    }
    return jsonResult({
      output_file: outputPath,
      result: payload,
      stdout_tail: result.stdout.slice(-4000),
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- stt_list_devices ---
server.registerTool("stt_list_devices", {
  description: "List available STT audio sources.",
  inputSchema: {
    repo_path: z.string().optional(),
  },
  annotations: { readOnlyHint: true, destructiveHint: false },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    let payload: Record<string, unknown> = {};
    try {
      const result = await runSttCli(repo, ["--list-devices"], 30);
      const text = result.stdout.trim();
      if (text) {
        const start = text.indexOf("{");
        const end = text.lastIndexOf("}");
        if (start >= 0 && end > start) {
          payload = JSON.parse(text.slice(start, end + 1)) as Record<string, unknown>;
        }
      }
    } catch (err: unknown) {
      payload = { warning: `Failed to enumerate endpoint devices: ${err instanceof Error ? err.message : String(err)}` };
    }
    return jsonResult({
      sources: [
        { id: "microphone", label: "Microphone" },
        { id: "loopback", label: "System Loopback" },
      ],
      ...payload,
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- stt_start_session ---
server.registerTool("stt_start_session", {
  description: "Start a continuous STT session and return a session_id.",
  inputSchema: {
    source: z.enum(["microphone", "loopback"]).default("microphone").optional(),
    mic_device_id: z.string().optional(),
    mic_device_name: z.string().optional(),
    model: z.string().default("nova-2").optional(),
    language: z.string().default("en").optional(),
    sample_rate: z.number().int().min(8000).default(16000).optional(),
    endpointing_ms: z.number().int().min(0).default(300).optional(),
    utterance_end_ms: z.number().int().min(0).default(1000).optional(),
    diarize: z.boolean().default(false).optional(),
    chunk_seconds: z.number().int().min(1).default(4).optional(),
    repo_path: z.string().optional(),
  },
}, async (input) => {
  try {
    const repo = resolveRepo(input.repo_path);
    const source = input.source ?? "microphone";
    const sessionId = `stt-${crypto.randomUUID().replace(/-/g, "")}`;

    const session = createSession({
      session_id: sessionId,
      repo,
      source,
      mic_device_id: input.mic_device_id ?? null,
      mic_device_name: input.mic_device_name ?? null,
      model: input.model ?? "nova-2",
      language: input.language ?? "en",
      sample_rate: Math.max(8000, input.sample_rate ?? 16000),
      endpointing_ms: Math.max(0, input.endpointing_ms ?? 300),
      utterance_end_ms: Math.max(0, input.utterance_end_ms ?? 1000),
      diarize: input.diarize ?? false,
      chunk_seconds: Math.max(1, input.chunk_seconds ?? 4),
      created_utc: utcNow(),
    });

    // Start background capture
    startSttCapture(session);

    return jsonResult({
      session_id: sessionId,
      status: session.status,
      created_utc: session.created_utc,
      source: session.source,
      mic_device_id: session.mic_device_id,
      mic_device_name: session.mic_device_name,
    });
  } catch (err: unknown) {
    return errorResult(err instanceof Error ? err.message : String(err));
  }
});

// --- stt_get_updates ---
server.registerTool("stt_get_updates", {
  description: "Poll incremental STT events from a running session.",
  inputSchema: {
    session_id: z.string().min(1),
    since_seq: z.number().int().min(0).default(0).optional(),
    limit: z.number().int().min(1).max(500).default(100).optional(),
  },
  annotations: { readOnlyHint: true, destructiveHint: false },
}, async (input) => {
  const session = getSession(input.session_id);
  if (!session) return errorResult(`Unknown session_id: ${input.session_id}`);

  const sinceSeq = input.since_seq ?? 0;
  const limit = input.limit ?? 100;
  const filtered = session.events.filter((e) => e.seq > sinceSeq);
  const selected = filtered.slice(0, limit);
  const nextSeq = selected.length > 0 ? selected[selected.length - 1].seq : sinceSeq;

  return jsonResult({
    session_id: input.session_id,
    status: session.status,
    events: selected,
    next_seq: nextSeq,
  });
});

// --- stt_get_session ---
server.registerTool("stt_get_session", {
  description: "Get current STT session status and counters.",
  inputSchema: {
    session_id: z.string().min(1),
  },
  annotations: { readOnlyHint: true, destructiveHint: false },
}, async (input) => {
  const session = getSession(input.session_id);
  if (!session) return errorResult(`Unknown session_id: ${input.session_id}`);

  return jsonResult({
    session_id: session.session_id,
    status: session.status,
    created_utc: session.created_utc,
    source: session.source,
    mic_device_id: session.mic_device_id,
    mic_device_name: session.mic_device_name,
    model: session.model,
    language: session.language,
    chunk_seconds: session.chunk_seconds,
    next_seq: session.next_seq,
    stable_chunk_count: session.stable_chunk_count,
    latest_transcript: session.latest_transcript,
    error_count: session.error_count,
  });
});

// --- stt_stop_session ---
server.registerTool("stt_stop_session", {
  description: "Stop an STT session.",
  inputSchema: {
    session_id: z.string().min(1),
  },
}, async (input) => {
  const session = getSession(input.session_id);
  if (!session) return errorResult(`Unknown session_id: ${input.session_id}`);

  session.stopped = true;
  if (session.process && !session.process.killed) {
    session.process.kill();
  }
  session.status = "stopped";
  pushEvent(session, "info", { message: "stt session stopped" });

  return jsonResult({
    session_id: input.session_id,
    status: session.status,
    stable_chunk_count: session.stable_chunk_count,
    error_count: session.error_count,
  });
});

// --- STT capture loop (background) ---
function startSttCapture(session: SttSession): void {
  pushEvent(session, "info", { message: "stt session started", source: session.source, mode: "stream" });

  const args = [
    "--stream-events",
    "--source", session.source,
    "--sample-rate", String(session.sample_rate),
    "--model", session.model,
    "--language", session.language,
    "--endpointing-ms", String(session.endpointing_ms),
    "--utterance-end-ms", String(session.utterance_end_ms),
    "--diarize", session.diarize ? "true" : "false",
    ...(session.source === "microphone" && session.mic_device_id ? ["--mic-device-id", session.mic_device_id] : []),
    ...(session.source === "microphone" && session.mic_device_name ? ["--mic-device-name", session.mic_device_name] : []),
  ];

  const command = dotnetRunCommand(session.repo, STT_CLI_PROJECT, args);
  const child = spawn(command[0], command.slice(1), {
    cwd: session.repo,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  session.process = child;
  pushEvent(session, "info", { message: "stream_process_started", pid: child.pid });

  let buffer = "";

  child.stdout?.on("data", (chunk: Buffer) => {
    if (session.stopped) return;
    buffer += chunk.toString("utf-8");
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const text = line.trim();
      if (!text) continue;

      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(text) as Record<string, unknown>;
      } catch {
        pushEvent(session, "info", { message: "stream_log", line: text.slice(-300) });
        continue;
      }

      const eventName = String(payload.event ?? "").trim().toLowerCase();

      if (eventName === "utterance_final") {
        const finalText = String(payload.text ?? "").trim();
        if (finalText) {
          session.latest_transcript = finalText;
          session.stable_chunk_count++;
          pushEvent(session, "utterance_final", { text: finalText, reason: payload.reason });
        }
      } else if (eventName === "error") {
        session.error_count++;
        pushEvent(session, "error", { message: String(payload.message ?? "") });
      } else {
        pushEvent(session, "info", { message: eventName || "stream_event", payload });
      }
    }
  });

  child.stderr?.on("data", (chunk: Buffer) => {
    if (session.stopped) return;
    pushEvent(session, "info", { message: "stream_stderr", line: chunk.toString("utf-8").slice(-300) });
  });

  child.on("close", (code) => {
    if (code !== 0 && !session.stopped) {
      session.error_count++;
      pushEvent(session, "error", { message: `stream process exited with code ${code}` });
    }
    session.status = "stopped";
    pushEvent(session, "info", { message: "stt session stopped" });
  });

  child.on("error", (err) => {
    session.error_count++;
    pushEvent(session, "error", { message: err.message, kind: "stream_failed" });
    session.status = "stopped";
  });
}

// --- Start server ---
startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start interview-assist server");
  process.exit(1);
});
