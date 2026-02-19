from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

DEFAULT_INTERVIEW_ASSIST_REPO = r"C:\Users\steph\source\repos\interview-assist-2"
TRANSCRIPTION_CONSOLE_PROJECT = Path(
    "Interview-assist-transcription-detection-console/Interview-assist-transcription-detection-console.csproj"
)
STT_CLI_PROJECT = Path("Interview-assist-stt-cli/Interview-assist-stt-cli.csproj")

mcp = FastMCP("interview-assist")


@dataclass
class SttEvent:
    seq: int
    type: str
    timestamp_utc: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "timestamp_utc": self.timestamp_utc,
            **self.payload,
        }


@dataclass
class SttSession:
    session_id: str
    repo: Path
    source: str
    mic_device_id: str | None
    mic_device_name: str | None
    model: str
    language: str
    sample_rate: int
    endpointing_ms: int
    utterance_end_ms: int
    diarize: bool
    chunk_seconds: int
    created_utc: str
    status: str = "running"
    next_seq: int = 1
    events: list[SttEvent] = field(default_factory=list)
    stable_chunk_count: int = 0
    latest_transcript: str = ""
    pending_text: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    worker: threading.Thread | None = None
    process: subprocess.Popen[str] | None = None
    error_count: int = 0


_stt_lock = threading.Lock()
_stt_sessions: dict[str, SttSession] = {}
_MAX_EVENTS_PER_SESSION = 2000


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _push_stt_event(session: SttSession, event_type: str, payload: dict[str, Any] | None = None) -> None:
    event = SttEvent(
        seq=session.next_seq,
        type=event_type,
        timestamp_utc=_utc_now(),
        payload=payload or {},
    )
    session.next_seq += 1
    session.events.append(event)
    if len(session.events) > _MAX_EVENTS_PER_SESSION:
        session.events = session.events[-_MAX_EVENTS_PER_SESSION:]


def _append_pending_text(session: SttSession, text: str) -> None:
    clean = text.strip()
    if not clean:
        return
    if not session.pending_text:
        session.pending_text = clean
        return
    # Avoid obvious duplication from repeated interim/stable text.
    if clean in session.pending_text:
        return
    if session.pending_text in clean:
        session.pending_text = clean
        return
    session.pending_text = f"{session.pending_text} {clean}".strip()


def _flush_pending_utterance(session: SttSession, reason: str) -> None:
    text = session.pending_text.strip()
    if not text:
        return
    _push_stt_event(
        session,
        "utterance_final",
        {
            "text": text,
            "reason": reason,
        },
    )
    session.pending_text = ""


def _stt_capture_loop(session: SttSession) -> None:
    _push_stt_event(
        session,
        "info",
        {
            "message": "stt session started",
            "source": session.source,
            "mode": "stream",
        },
    )
    args = [
        "--stream-events",
        "--source",
        session.source,
        "--sample-rate",
        str(max(8000, session.sample_rate)),
        "--model",
        session.model,
        "--language",
        session.language,
        "--endpointing-ms",
        str(max(0, session.endpointing_ms)),
        "--utterance-end-ms",
        str(max(0, session.utterance_end_ms)),
        "--diarize",
        "true" if session.diarize else "false",
        *(
            ["--mic-device-id", session.mic_device_id]
            if session.source == "microphone" and session.mic_device_id
            else []
        ),
        *(
            ["--mic-device-name", session.mic_device_name]
            if session.source == "microphone" and session.mic_device_name
            else []
        ),
    ]
    command = _dotnet_run_command(session.repo, STT_CLI_PROJECT, args)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(session.repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        session.process = process
        _push_stt_event(session, "info", {"message": "stream_process_started", "pid": process.pid})
        while not session.stop_event.is_set():
            if process.stdout is None:
                break
            line = process.stdout.readline()
            if line == "":
                if process.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                _push_stt_event(session, "info", {"message": "stream_log", "line": text[-300:]})
                continue
            event_name = str(payload.get("event", "")).strip().lower()
            if event_name == "utterance_final":
                final_text = str(payload.get("text", "")).strip()
                if final_text:
                    session.latest_transcript = final_text
                    session.stable_chunk_count += 1
                    _push_stt_event(
                        session,
                        "utterance_final",
                        {
                            "text": final_text,
                            "reason": payload.get("reason"),
                        },
                    )
            elif event_name == "error":
                session.error_count += 1
                _push_stt_event(session, "error", {"message": str(payload.get("message", ""))})
            elif event_name in {"warning", "info", "session_started", "session_stopped", "stable_text", "provisional_text"}:
                _push_stt_event(session, "info", {"message": event_name, "payload": payload})
            else:
                _push_stt_event(session, "info", {"message": "stream_event", "event": event_name, "payload": payload})
        if process.poll() is None:
            with contextlib.suppress(Exception):
                process.terminate()
                process.wait(timeout=3)
        if process.poll() not in (0, None) and not session.stop_event.is_set():
            session.error_count += 1
            _push_stt_event(session, "error", {"message": f"stream process exited with code {process.returncode}"})
    except Exception as ex:
        session.error_count += 1
        _push_stt_event(session, "error", {"message": str(ex), "kind": "stream_failed"})
    finally:
        session.status = "stopped"
        _push_stt_event(session, "info", {"message": "stt session stopped"})


def _parse_stt_cli_payload(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Some CLI runs include informational lines before/after JSON.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        fragment = text[start : end + 1]
        parsed = json.loads(fragment)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("STT CLI did not return JSON payload")


def _extract_transcript_fields(payload: dict[str, Any]) -> tuple[str, str, list[Any]]:
    def _first_non_empty(candidates: list[str]) -> str:
        for key in candidates:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    stable_text = _first_non_empty(
        [
            "StableTranscript",
            "stableTranscript",
            "stable_transcript",
            "FinalTranscript",
            "finalTranscript",
            "final_transcript",
            "Transcript",
            "transcript",
            "text",
        ]
    )
    provisional_text = _first_non_empty(
        [
            "ProvisionalTranscript",
            "provisionalTranscript",
            "provisional_transcript",
            "InterimTranscript",
            "interimTranscript",
            "interim_transcript",
        ]
    )
    stable_chunks = (
        payload.get("StableChunks")
        or payload.get("stableChunks")
        or payload.get("stable_chunks")
        or []
    )
    if not isinstance(stable_chunks, list):
        stable_chunks = []
    return stable_text, provisional_text, stable_chunks


def _payload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in ("StableTranscript", "ProvisionalTranscript", "Transcript", "text", "Error", "error"):
        if key in payload:
            value = payload.get(key)
            if isinstance(value, str) and len(value) > 120:
                preview[key] = value[:117] + "..."
            else:
                preview[key] = value
    for key in ("StableChunks", "stableChunks"):
        if key in payload:
            value = payload.get(key)
            if isinstance(value, list):
                preview[key] = f"list[{len(value)}]"
            else:
                preview[key] = type(value).__name__
    return preview


def _resolve_repo(repo_path: str | None) -> Path:
    selected = (repo_path or os.environ.get("INTERVIEW_ASSIST_REPO") or DEFAULT_INTERVIEW_ASSIST_REPO).strip()
    repo = Path(selected).expanduser().resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Interview Assist repo does not exist: {repo}")
    if not repo.is_dir():
        raise NotADirectoryError(f"Interview Assist repo is not a directory: {repo}")
    project = repo / TRANSCRIPTION_CONSOLE_PROJECT
    if not project.exists():
        raise FileNotFoundError(f"Transcription detection project not found: {project}")
    return repo


def _run_dotnet_project(
    repo: Path,
    project_relative_path: Path,
    args: list[str],
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    project = repo / project_relative_path
    if not project.exists():
        raise FileNotFoundError(f"Project not found: {project}")
    command = _dotnet_run_command(repo, project_relative_path, args)
    completed = subprocess.run(
        command,
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, timeout_seconds),
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    result = {
        "command": command,
        "cwd": str(repo),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if completed.returncode != 0:
        raise RuntimeError(
            "Interview Assist command failed"
            f"\nexit_code: {completed.returncode}"
            f"\nstdout_tail: {stdout[-2000:]}"
            f"\nstderr_tail: {stderr[-2000:]}"
        )
    return result


def _dotnet_run_command(
    repo: Path,
    project_relative_path: Path,
    args: list[str],
) -> list[str]:
    project = repo / project_relative_path
    return [
        "dotnet",
        "run",
        "--no-build",
        "--project",
        str(project),
        "--",
        *args,
    ]


def _run_interview_assist(
    repo: Path,
    args: list[str],
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    return _run_dotnet_project(repo, TRANSCRIPTION_CONSOLE_PROJECT, args, timeout_seconds=timeout_seconds)


def _run_stt_cli(
    repo: Path,
    args: list[str],
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    return _run_dotnet_project(repo, STT_CLI_PROJECT, args, timeout_seconds=timeout_seconds)


def _find_output_line_value(output: str, prefix: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(prefix)}\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(output)
    if match is None:
        return None
    return match.group(1).strip()


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _evaluation_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {}
    metrics = report.get("Metrics", {})
    subtype = report.get("SubtypeAccuracy", {})
    return {
        "generated_at": report.get("GeneratedAt"),
        "session_file": report.get("SessionFile"),
        "ground_truth_source": report.get("GroundTruthSource"),
        "metrics": {
            "true_positives": metrics.get("TruePositives"),
            "false_positives": metrics.get("FalsePositives"),
            "false_negatives": metrics.get("FalseNegatives"),
            "precision": metrics.get("Precision"),
            "recall": metrics.get("Recall"),
            "f1_score": metrics.get("F1Score"),
        },
        "subtype_accuracy": {
            "overall_accuracy": subtype.get("OverallAccuracy"),
            "total_with_subtype": subtype.get("TotalWithSubtype"),
            "total_correct": subtype.get("TotalCorrect"),
        },
        "counts": {
            "matches": len(report.get("Matches", []) or []),
            "missed": len(report.get("Missed", []) or []),
            "false_alarms": len(report.get("FalseAlarms", []) or []),
        },
    }


def _temp_json_path(prefix: str) -> Path:
    return Path(tempfile.gettempdir()) / f"{prefix}-{uuid4().hex}.json"


@mcp.tool(description="Validate Interview Assist MCP prerequisites and return detected paths.")
def ia_healthcheck(repo_path: str | None = None) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    project = repo / TRANSCRIPTION_CONSOLE_PROJECT
    stt_project = repo / STT_CLI_PROJECT
    dotnet = subprocess.run(
        ["dotnet", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "repo_path": str(repo),
        "project_path": str(project),
        "stt_project_path": str(stt_project),
        "stt_project_exists": stt_project.exists(),
        "dotnet_version": (dotnet.stdout or "").strip(),
    }


@mcp.tool(description="List recording JSONL files in interview-assist-2 recordings folder.")
def ia_list_recordings(
    repo_path: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    recordings = repo / "recordings"
    if not recordings.exists():
        return {"recordings_dir": str(recordings), "files": []}
    files = sorted(recordings.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    selected = files[: max(1, limit)]
    return {
        "recordings_dir": str(recordings),
        "files": [
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": path.stat().st_size,
            }
            for path in selected
        ],
    }


@mcp.tool(description="Generate markdown report for a session JSONL using interview-assist-2 analyze mode.")
def ia_analyze_session(
    session_file: str,
    repo_path: str | None = None,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    result = _run_interview_assist(repo, ["--analyze", session_file], timeout_seconds=timeout_seconds)
    report_path = _find_output_line_value(result["stdout"], "Report:")
    return {
        "report_path": report_path,
        "exit_code": result["exit_code"],
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="Run evaluation on a session JSONL and return key precision/recall/F1 metrics.")
def ia_evaluate_session(
    session_file: str,
    output_file: str | None = None,
    model: str | None = None,
    ground_truth_file: str | None = None,
    repo_path: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    output_path = Path(output_file).expanduser().resolve() if output_file else _temp_json_path("ia-eval")
    args = ["--evaluate", session_file, "--output", str(output_path)]
    if model:
        args.extend(["--model", model])
    if ground_truth_file:
        args.extend(["--ground-truth", ground_truth_file])
    result = _run_interview_assist(repo, args, timeout_seconds=timeout_seconds)
    report = _safe_load_json(output_path)
    return {
        "output_file": str(output_path),
        "summary": _evaluation_summary(report),
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="Compare heuristic/LLM/parallel detection strategies for a session JSONL.")
def ia_compare_strategies(
    session_file: str,
    output_file: str | None = None,
    repo_path: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    output_path = Path(output_file).expanduser().resolve() if output_file else _temp_json_path("ia-compare")
    args = ["--compare", session_file, "--output", str(output_path)]
    result = _run_interview_assist(repo, args, timeout_seconds=timeout_seconds)
    compare_json = _safe_load_json(output_path)
    return {
        "output_file": str(output_path),
        "comparison": compare_json,
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="Tune detection confidence threshold using optimize target f1/precision/recall/balanced.")
def ia_tune_threshold(
    session_file: str,
    optimize: str = "f1",
    repo_path: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    args = ["--tune-threshold", session_file, "--optimize", optimize]
    result = _run_interview_assist(repo, args, timeout_seconds=timeout_seconds)
    return {
        "optimize": optimize,
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="Run regression test for a session against a baseline file.")
def ia_regression_test(
    baseline_file: str,
    data_file: str,
    repo_path: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    args = ["--regression", baseline_file, "--data", data_file]
    result = _run_interview_assist(repo, args, timeout_seconds=timeout_seconds)
    return {
        "baseline_file": baseline_file,
        "data_file": data_file,
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="Create baseline JSON from a session JSONL file.")
def ia_create_baseline(
    data_file: str,
    output_file: str,
    version: str = "1.0",
    repo_path: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    output_path = Path(output_file).expanduser().resolve()
    args = ["--create-baseline", str(output_path), "--data", data_file, "--version", version]
    result = _run_interview_assist(repo, args, timeout_seconds=timeout_seconds)
    baseline = _safe_load_json(output_path)
    return {
        "output_file": str(output_path),
        "baseline": baseline,
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="Capture live microphone or loopback audio once and transcribe via Deepgram.")
def ia_transcribe_once(
    duration_seconds: int = 8,
    source: str = "microphone",
    mic_device_id: str | None = None,
    mic_device_name: str | None = None,
    sample_rate: int = 16000,
    model: str = "nova-2",
    language: str = "en",
    endpointing_ms: int = 300,
    utterance_end_ms: int = 1000,
    diarize: bool = False,
    output_file: str | None = None,
    repo_path: str | None = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    args = [
        "--duration-seconds",
        str(max(1, duration_seconds)),
        "--source",
        source,
        *(
            ["--mic-device-id", mic_device_id]
            if source == "microphone" and mic_device_id
            else []
        ),
        *(
            ["--mic-device-name", mic_device_name]
            if source == "microphone" and mic_device_name
            else []
        ),
        "--sample-rate",
        str(max(8000, sample_rate)),
        "--model",
        model,
        "--language",
        language,
        "--endpointing-ms",
        str(max(0, endpointing_ms)),
        "--utterance-end-ms",
        str(max(0, utterance_end_ms)),
        "--diarize",
        "true" if diarize else "false",
    ]
    output_path: Path | None = None
    if output_file:
        output_path = Path(output_file).expanduser().resolve()
        args.extend(["--output", str(output_path)])
    result = _run_stt_cli(repo, args, timeout_seconds=timeout_seconds)
    payload = _safe_load_json(output_path) if output_path else None
    if payload is None:
        try:
            payload = json.loads(result["stdout"])
        except json.JSONDecodeError:
            payload = None
    return {
        "output_file": str(output_path) if output_path else None,
        "result": payload,
        "stdout_tail": result["stdout"][-4000:],
    }


@mcp.tool(description="List available STT audio sources.")
def stt_list_devices(repo_path: str | None = None) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    try:
        result = _run_stt_cli(repo, ["--list-devices"], timeout_seconds=30)
        payload = _parse_stt_cli_payload(result["stdout"])
    except Exception as ex:
        payload = {"warning": f"Failed to enumerate endpoint devices: {ex}"}
    return {
        "sources": [
            {"id": "microphone", "label": "Microphone"},
            {"id": "loopback", "label": "System Loopback"},
        ],
        **payload,
    }


@mcp.tool(description="Start a continuous STT session and return a session_id.")
def stt_start_session(
    source: str = "microphone",
    mic_device_id: str | None = None,
    mic_device_name: str | None = None,
    model: str = "nova-2",
    language: str = "en",
    sample_rate: int = 16000,
    endpointing_ms: int = 300,
    utterance_end_ms: int = 1000,
    diarize: bool = False,
    chunk_seconds: int = 4,
    repo_path: str | None = None,
) -> dict[str, Any]:
    repo = _resolve_repo(repo_path)
    session_id = f"stt-{uuid4().hex}"
    session = SttSession(
        session_id=session_id,
        repo=repo,
        source=source,
        mic_device_id=mic_device_id,
        mic_device_name=mic_device_name,
        model=model,
        language=language,
        sample_rate=max(8000, sample_rate),
        endpointing_ms=max(0, endpointing_ms),
        utterance_end_ms=max(0, utterance_end_ms),
        diarize=diarize,
        chunk_seconds=max(1, chunk_seconds),
        created_utc=_utc_now(),
    )
    worker = threading.Thread(target=_stt_capture_loop, args=(session,), daemon=True)
    session.worker = worker
    with _stt_lock:
        _stt_sessions[session_id] = session
    worker.start()
    return {
        "session_id": session_id,
        "status": session.status,
        "created_utc": session.created_utc,
        "source": session.source,
        "mic_device_id": session.mic_device_id,
        "mic_device_name": session.mic_device_name,
    }


@mcp.tool(description="Poll incremental STT events from a running session.")
def stt_get_updates(
    session_id: str,
    since_seq: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    with _stt_lock:
        session = _stt_sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        filtered = [evt.to_dict() for evt in session.events if evt.seq > since_seq]
    selected = filtered[: max(1, min(limit, 500))]
    next_seq = selected[-1]["seq"] if selected else since_seq
    return {
        "session_id": session_id,
        "status": session.status,
        "events": selected,
        "next_seq": next_seq,
    }


@mcp.tool(description="Get current STT session status and counters.")
def stt_get_session(session_id: str) -> dict[str, Any]:
    with _stt_lock:
        session = _stt_sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        return {
            "session_id": session.session_id,
            "status": session.status,
            "created_utc": session.created_utc,
            "source": session.source,
            "mic_device_id": session.mic_device_id,
            "mic_device_name": session.mic_device_name,
            "model": session.model,
            "language": session.language,
            "chunk_seconds": session.chunk_seconds,
            "next_seq": session.next_seq,
            "stable_chunk_count": session.stable_chunk_count,
            "latest_transcript": session.latest_transcript,
            "error_count": session.error_count,
        }


@mcp.tool(description="Stop an STT session.")
def stt_stop_session(session_id: str) -> dict[str, Any]:
    with _stt_lock:
        session = _stt_sessions.get(session_id)
    if session is None:
        raise ValueError(f"Unknown session_id: {session_id}")
    session.stop_event.set()
    if session.worker is not None:
        session.worker.join(timeout=10)
    with _stt_lock:
        session.status = "stopped"
    return {
        "session_id": session_id,
        "status": session.status,
        "stable_chunk_count": session.stable_chunk_count,
        "error_count": session.error_count,
    }


if __name__ == "__main__":
    mcp.run()
