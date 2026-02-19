from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
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
    command = [
        "dotnet",
        "run",
        "--no-build",
        "--project",
        str(project),
        "--",
        *args,
    ]
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


if __name__ == "__main__":
    mcp.run()
