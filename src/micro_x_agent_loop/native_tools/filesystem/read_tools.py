"""F2 — native read-only filesystem tools: read_file, grep, glob.

Faithful Python port of the TS filesystem MCP tools. Preserves:
- exact ADR-023 truncation marker strings + structured fields,
- read_file line-numbering / binary sniff / .docx handling / splitLines,
- grep driving a real ripgrep binary (identical flags / .gitignore / type
  behaviour) with the same count/head-limit/marker logic,
- glob: mtime-desc, onlyFiles, dot=false, head-limit + marker.

No char-level truncation here (ADR-024: the agent's ToolResultOverrides is
the only char-truncation layer). The head/line limits below are the tool's
own pagination (ADR-023), not result truncation.

Tools take an injected PathPolicy; they are wired into bootstrap only at
the F6 atomic flip, so the running MCP filesystem is undisturbed until then.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from typing import Any

from micro_x_agent_loop.native_tools.filesystem.paths import (
    PathPolicy,
    resolve_allowed,
)
from micro_x_agent_loop.tool import ToolResult

_DEFAULT_LIMIT = 2000
_MAX_LIMIT = 10000
_BINARY_SNIFF_BYTES = 8 * 1024
_LINE_NUM_WIDTH = 6
_DEFAULT_HEAD_LIMIT = 250
_MAX_HEAD_LIMIT = 5000
_RG_TIMEOUT_S = 30


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def _split_lines(text: str) -> list[str]:
    if text == "":
        return []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _is_binary(buf: bytes) -> bool:
    return 0 in buf[:_BINARY_SNIFF_BYTES]


def _read_docx(path: str) -> str:
    import docx  # noqa: PLC0415

    return "\n".join(p.text for p in docx.Document(path).paragraphs)


class ReadFileTool:
    def __init__(self, policy: PathPolicy) -> None:
        self._policy = policy

    @property
    def name(self) -> str:
        return "filesystem__read_file"

    @property
    def description(self) -> str:
        return (
            "Read a file as cat -n-style line-numbered text. Supports plain text and "
            ".docx documents. Prefer grep when you only need specific lines/patterns. "
            "Use offset and limit for large files (default first 2000 lines). Path must "
            "be inside the allowed roots. Binary files are refused."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "offset": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        offset = int(tool_input.get("offset") or 1)
        limit = int(tool_input.get("limit") or _DEFAULT_LIMIT)
        try:
            resolved = resolve_allowed(self._policy, tool_input.get("path"), must_exist=True)
            if resolved.lower().endswith(".docx"):
                raw = _read_docx(resolved)
            else:
                with open(resolved, "rb") as fh:
                    buf = fh.read()
                if _is_binary(buf):
                    return ToolResult(
                        text=(
                            f"refusing to read binary file: {resolved} "
                            f"(null byte detected in first {_BINARY_SNIFF_BYTES} bytes)"
                        ),
                        is_error=True,
                    )
                raw = buf.decode("utf-8", errors="replace")

            all_lines = _split_lines(raw)
            total = len(all_lines)
            size_bytes = len(raw.encode("utf-8"))
            start_idx = offset - 1
            end_idx = min(start_idx + limit, total)
            sliced = all_lines[start_idx:end_idx] if start_idx < total else []
            start_line = offset if sliced else 0
            end_line = offset + len(sliced) - 1 if sliced else 0
            truncated = end_idx < total

            if total == 0:
                formatted = "(file is empty)"
            elif not sliced:
                formatted = f"(offset {offset} is past end of file — file has {total} lines)"
            else:
                body = "\n".join(
                    f"{str(offset + i).rjust(_LINE_NUM_WIDTH)}\t{line}"
                    for i, line in enumerate(sliced)
                )
                formatted = body
                if truncated:
                    shown_bytes = len("\n".join(sliced).encode("utf-8"))
                    line_pct = max(1, round((len(sliced) / total) * 100))
                    next_offset = end_line + 1
                    formatted += (
                        f"\n\n[Output truncated: showed lines {start_line}-{end_line} "
                        f"of {total} ({line_pct}%, {_format_bytes(shown_bytes)} of "
                        f"{_format_bytes(size_bytes)}).\n"
                        f' To read more: read_file(path="{resolved}", '
                        f"offset={next_offset}, limit={limit})]"
                    )

            return ToolResult(
                text=formatted,
                structured={
                    "content": formatted,
                    "path": resolved,
                    "size_bytes": size_bytes,
                    "total_lines": total,
                    "start_line": start_line,
                    "end_line": end_line,
                    "truncated": truncated,
                },
            )
        except Exception as ex:
            return ToolResult(text=f"Error reading file: {ex}", is_error=True)


def _resolve_rg() -> str:
    """Resolve a ripgrep binary. Order: explicit override → project-managed
    `.tools/rg/` (scripts/fetch_ripgrep.py, ADR-025 mechanism (i)) →
    legacy @vscode/ripgrep bundle → PATH. Clear error otherwise."""
    env = os.environ.get("FILESYSTEM_RG_PATH")
    if env and os.path.isfile(env):
        return env

    here = os.path.dirname(__file__)
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))

    managed = os.path.join(
        repo_root, ".tools", "rg", "rg.exe" if os.name == "nt" else "rg"
    )
    if os.path.isfile(managed):
        return managed

    bundled = os.path.join(
        repo_root, "mcp_servers", "ts", "packages", "filesystem",
        "node_modules", "@vscode", "ripgrep", "bin",
        "rg.exe" if os.name == "nt" else "rg",
    )
    if os.path.isfile(bundled):
        return bundled

    found = shutil.which("rg")
    if found:
        return found

    raise RuntimeError(
        "ripgrep not found. Run `python scripts/fetch_ripgrep.py` to "
        "provision it into .tools/rg/ (or set FILESYSTEM_RG_PATH, or put "
        "rg on PATH)."
    )


def _sum_counts(lines: list[str]) -> int:
    total = 0
    for line in lines:
        tail = line.split(":")[-1] if ":" in line else line
        try:
            total += int(tail)
        except ValueError:
            pass
    return total


class GrepTool:
    def __init__(self, policy: PathPolicy) -> None:
        self._policy = policy

    @property
    def name(self) -> str:
        return "filesystem__grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents using ripgrep. Respects .gitignore. output_mode: "
            "content (matching lines), files_with_matches (default, filenames), "
            "count (per-file counts). EXCEPTION — single-line files (minified JSON, "
            "RSS, one-line HTML): this is line-oriented; count returns 1 and content "
            "returns the whole file as one line. For occurrence counts on such "
            "content use bash `grep -o PATTERN file | wc -l`."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string"},
                "glob": {"type": "string"},
                "type": {"type": "string"},
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "default": "files_with_matches",
                },
                "case_insensitive": {"type": "boolean", "default": False},
                "line_numbers": {"type": "boolean", "default": True},
                "context": {"type": "integer", "minimum": 0, "maximum": 20},
                "multiline": {"type": "boolean", "default": False},
                "head_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_HEAD_LIMIT,
                    "default": _DEFAULT_HEAD_LIMIT,
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    def _build_args(self, ti: dict[str, Any], search_path: str) -> list[str]:
        mode = ti.get("output_mode", "files_with_matches")
        args: list[str] = []
        if mode == "files_with_matches":
            args.append("--files-with-matches")
        elif mode == "count":
            args.append("--count-matches")
        else:  # content
            if ti.get("line_numbers", True):
                args.append("--line-number")
            if ti.get("context") is not None:
                args.append(f"--context={int(ti['context'])}")
        if ti.get("case_insensitive", False):
            args.append("--ignore-case")
        if ti.get("multiline", False):
            args += ["--multiline", "--multiline-dotall"]
        if ti.get("glob"):
            args += ["--glob", ti["glob"]]
        if ti.get("type"):
            args += ["--type", ti["type"]]
        args += ["--", ti["pattern"], search_path]
        return args

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        mode = tool_input.get("output_mode", "files_with_matches")
        head_limit = int(tool_input.get("head_limit") or _DEFAULT_HEAD_LIMIT)
        try:
            search_path = resolve_allowed(self._policy, tool_input.get("path"), must_exist=True)
            rg = _resolve_rg()
            try:
                # subprocess.run blocks; run it in a worker thread so the
                # event loop stays responsive (called from async execute).
                proc = await asyncio.to_thread(
                    subprocess.run,
                    [rg, *self._build_args(tool_input, search_path)],
                    capture_output=True,
                    text=True,
                    timeout=_RG_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as ex:
                raise RuntimeError(f"timed out after {_RG_TIMEOUT_S}s") from ex
            if proc.returncode == 2:
                raise RuntimeError(proc.stdout or proc.stderr or "ripgrep error")

            stdout = proc.stdout
            lines = [ln for ln in stdout.split("\n") if ln] if stdout else []
            total_count = _sum_counts(lines) if mode == "count" else len(lines)
            truncated = len(lines) > head_limit
            kept = lines[:head_limit] if truncated else lines
            results = "\n".join(kept)

            if not results:
                text = "(no matches)"
            elif truncated:
                pct = max(1, round((head_limit / len(lines)) * 100))
                bumped = min(_MAX_HEAD_LIMIT, len(lines))
                esc = tool_input["pattern"].replace('"', '\\"')
                path_arg = f', path="{tool_input["path"]}"' if tool_input.get("path") else ""
                text = (
                    results
                    + f"\n\n[Output truncated: showed first {head_limit} of "
                    f"{len(lines)} matches ({pct}%).\n"
                    f' To see more: grep(pattern="{esc}"{path_arg}, '
                    f"head_limit={bumped}) — or narrow with glob/type/pattern]"
                )
            else:
                text = results

            return ToolResult(
                text=text,
                structured={
                    "mode": mode,
                    "results": results,
                    "match_count": total_count,
                    "truncated": truncated,
                },
            )
        except Exception as ex:
            return ToolResult(text=f"grep error: {ex}", is_error=True)


def _expand_braces(pattern: str) -> list[str]:
    """Minimal single-level {a,b,c} expansion (covers the documented
    fast-glob patterns; nested braces are not used in practice)."""
    i = pattern.find("{")
    if i == -1:
        return [pattern]
    j = pattern.find("}", i)
    if j == -1:
        return [pattern]
    head, body, tail = pattern[:i], pattern[i + 1 : j], pattern[j + 1 :]
    out: list[str] = []
    for opt in body.split(","):
        out.extend(_expand_braces(head + opt + tail))
    return out


class GlobTool:
    def __init__(self, policy: PathPolicy) -> None:
        self._policy = policy

    @property
    def name(self) -> str:
        return "filesystem__glob"

    @property
    def description(self) -> str:
        return (
            'Find files by name pattern (e.g. "**/*.ts", "src/**/*.{js,jsx}"). '
            "Returns absolute paths sorted by mtime (newest first), files only, "
            "within the allowed roots. Use this — not bash find — to discover files."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string"},
                "head_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_HEAD_LIMIT,
                    "default": _DEFAULT_HEAD_LIMIT,
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        import glob as _glob  # noqa: PLC0415

        head_limit = int(tool_input.get("head_limit") or _DEFAULT_HEAD_LIMIT)
        try:
            root = resolve_allowed(self._policy, tool_input.get("path"), must_exist=True)
            seen: set[str] = set()
            for pat in _expand_braces(tool_input["pattern"]):
                for m in _glob.glob(os.path.join(root, pat), recursive=True):
                    if not os.path.isfile(m):
                        continue
                    rel = os.path.relpath(m, root)
                    # dot=false: skip hidden path components
                    if any(seg.startswith(".") for seg in rel.split(os.sep)):
                        continue
                    seen.add(os.path.abspath(m))

            def _mtime(p: str) -> float:
                try:
                    return os.stat(p).st_mtime
                except OSError:
                    return 0.0

            ordered = sorted(seen, key=_mtime, reverse=True)
            truncated = len(ordered) > head_limit
            kept = ordered[:head_limit] if truncated else ordered

            if not kept:
                text = "(no matches)"
            elif truncated:
                pct = max(1, round((head_limit / len(ordered)) * 100))
                bumped = min(_MAX_HEAD_LIMIT, len(ordered))
                esc = tool_input["pattern"].replace('"', '\\"')
                path_arg = f', path="{tool_input["path"]}"' if tool_input.get("path") else ""
                text = (
                    "\n".join(kept)
                    + f"\n\n[Output truncated: showed first {head_limit} of "
                    f"{len(ordered)} paths ({pct}%).\n"
                    f' To see more: glob(pattern="{esc}"{path_arg}, '
                    f"head_limit={bumped}) — or narrow the pattern]"
                )
            else:
                text = "\n".join(kept)

            return ToolResult(
                text=text,
                structured={"paths": kept, "total": len(ordered), "truncated": truncated},
            )
        except Exception as ex:
            return ToolResult(text=f"glob error: {ex}", is_error=True)


def build_read_tools(policy: PathPolicy) -> list[Any]:
    return [ReadFileTool(policy), GrepTool(policy), GlobTool(policy)]
