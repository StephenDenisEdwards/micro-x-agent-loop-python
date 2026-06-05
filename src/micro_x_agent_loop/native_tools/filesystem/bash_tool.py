"""F4 — native bash tool. Faithful port of the TS filesystem bash tool
(ADR-025). The security-sensitive one.

Preserves verbatim (logs/agent/tests depend on the exact strings):
- Git-for-Windows shell resolution (FILESYSTEM_BASH_SHELL override →
  POSIX /bin/bash → Git-for-Windows candidates → clear error),
- FILESYSTEM_BASH_PATH_GUARD (default ON) absolute/`..` containment scan,
- FILESYSTEM_BASH_ALLOWED_COMMANDS allowlist (unset / deny-all / list),
- 30 s timeout, 10 MB stdout+stderr cap with the ADR-023 output_truncated
  marker, combined-output text assembly, is_error semantics.

Deliberate, documented deviation from the TS: shell resolution is LAZY
(first execute, cached) rather than at module load. The TS raises at
registration; in-process that would kill read_file/grep/glob too if no
bash exists. Lazy keeps the rest of the filesystem tools usable and
fails only when bash is actually invoked.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from typing import Any

from micro_x_agent_loop.native_tools.filesystem.paths import (
    PathPolicy,
    is_path_allowed,
)
from micro_x_agent_loop.tool import ToolResult

_IS_WINDOWS = os.name == "nt"
_TIMEOUT_S = 30
_MAX_BUFFER = 10 * 1024 * 1024
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_PREFIX = "\\\\"

_shell_cache: str | None = None


def _resolve_bash_shell() -> str:
    global _shell_cache
    if _shell_cache is not None:
        return _shell_cache
    override = (os.environ.get("FILESYSTEM_BASH_SHELL") or "").strip()
    if override:
        _shell_cache = override
        return override
    if not _IS_WINDOWS:
        _shell_cache = "/bin/bash"
        return _shell_cache
    candidates = [
        "C:\\Program Files\\Git\\bin\\bash.exe",
        "C:\\Program Files\\Git\\usr\\bin\\bash.exe",
        "C:\\Program Files (x86)\\Git\\bin\\bash.exe",
    ]
    pf = os.environ.get("PROGRAMFILES")
    if pf:
        candidates.append(f"{pf}\\Git\\bin\\bash.exe")
    for p in candidates:
        if os.path.isfile(p):
            _shell_cache = p
            return p
    raise RuntimeError(
        "filesystem__bash: no bash shell found. Install Git for Windows "
        "(https://git-scm.com/download/win) or set FILESYSTEM_BASH_SHELL "
        "to a bash binary."
    )


def _parse_env_bool(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    v = raw.strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return fallback


def _read_allowlist(name: str) -> tuple[str, set[str]]:
    raw = os.environ.get(name)
    if raw is None:
        return ("unset", set())
    trimmed = raw.strip()
    if trimmed == "":
        return ("deny_all", set())
    items = {s.strip() for s in trimmed.split(",") if s.strip()}
    return ("list", items)


def _extract_first_token(command: str) -> str | None:
    m = re.match(r"^\S+", command.strip())
    return m.group(0) if m else None


def _looks_like_absolute(token: str) -> bool:
    if _IS_WINDOWS:
        return bool(_WIN_DRIVE_RE.match(token)) or token.startswith(_UNC_PREFIX)
    return token.startswith("/") and len(token) > 1


def _looks_like_traversal(token: str) -> bool:
    n = token.replace("\\", "/")
    return n == ".." or n.startswith("../") or "/../" in n or n.endswith("/..")


def _find_path_candidates(command: str) -> list[str]:
    cleaned = re.sub(r"['\"]", " ", command)
    out: list[str] = []
    for raw in re.split(r"[\s=]+", cleaned):
        if not raw:
            continue
        token = raw.strip(";&|()<>{}")
        if not token:
            continue
        if _looks_like_absolute(token) or _looks_like_traversal(token):
            out.append(token)
    return out


def _check_path_guard(command: str, policy: PathPolicy) -> str | None:
    for cand in _find_path_candidates(command):
        if not is_path_allowed(policy, cand):
            sep = "; " if _IS_WINDOWS else ":"
            root_list = sep.join([policy.working_dir, *policy.extra_allowed])
            return (
                f'bash: refusing to execute — command references path "{cand}" '
                f"outside the allowed roots. Allowed: {root_list}. "
                "Set FILESYSTEM_BASH_PATH_GUARD=false to disable, or add the "
                "root to FILESYSTEM_ALLOWED_DIRS. (Accident prevention only — "
                "not adversarial sandboxing; see ISSUE-005.)"
            )
    return None


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


class BashTool:
    def __init__(self, policy: PathPolicy) -> None:
        self._policy = policy
        self._path_guard = _parse_env_bool("FILESYSTEM_BASH_PATH_GUARD", True)
        self._allow_mode, self._allow_set = _read_allowlist(
            "FILESYSTEM_BASH_ALLOWED_COMMANDS"
        )

    @property
    def name(self) -> str:
        return "filesystem__bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the workspace working directory "
            "(POSIX bash on every platform — Git for Windows on Windows). "
            "Use for tests / git / build tools / package managers and anything "
            "no dedicated tool covers. Do NOT use for filesystem work — use "
            "read_file / grep / glob / edit_file / write_file / append_file / "
            "delete_file. Containment is accident-prevention only: "
            "FILESYSTEM_BASH_PATH_GUARD (default on) rejects out-of-root "
            "absolute/`..` paths; FILESYSTEM_BASH_ALLOWED_COMMANDS restricts "
            "the first token; both are string-level and bypassable."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        }

    @property
    def is_mutating(self) -> bool:
        return True

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []  # cannot predict from an arbitrary command; faithful to MCP proxy

    def _refusal(self, text: str) -> ToolResult:
        return ToolResult(text=text, is_error=True)

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        command = tool_input.get("command", "")

        # 1. Allowlist
        if self._allow_mode == "deny_all":
            return self._refusal(
                "bash is disabled (FILESYSTEM_BASH_ALLOWED_COMMANDS is set to "
                "empty — kill switch). Unset the env var or list permitted "
                "first-tokens to re-enable."
            )
        if self._allow_mode == "list":
            first = _extract_first_token(command)
            if first is None:
                return self._refusal("bash: command is empty")
            if first not in self._allow_set:
                allowed = ", ".join(sorted(self._allow_set))
                return self._refusal(
                    f'bash: command "{first}" is not in '
                    f"FILESYSTEM_BASH_ALLOWED_COMMANDS allowlist (allowed: "
                    f"{allowed}). Note: only the first token is checked — "
                    "pipes / chains / subshells / command substitution are "
                    "not decomposed."
                )

        # 2. Path guard
        if self._path_guard:
            violation = _check_path_guard(command, self._policy)
            if violation is not None:
                return self._refusal(violation)

        # 3. Execute
        try:
            shell = _resolve_bash_shell()
        except RuntimeError as ex:
            return ToolResult(text=f"Error executing command: {ex}", is_error=True)

        timed_out = False
        output_truncated = False
        try:
            # subprocess.run blocks; run it in a worker thread so the event
            # loop stays responsive (this tool runs from within async execute).
            proc = await asyncio.to_thread(
                subprocess.run,
                [shell, "-c", command],
                cwd=self._policy.working_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT_S,
            )
            stdout, stderr = proc.stdout or "", proc.stderr or ""
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as ex:
            timed_out = True
            exit_code = -1
            stdout = ex.stdout or "" if isinstance(ex.stdout, str) else ""
            stderr = ex.stderr or "" if isinstance(ex.stderr, str) else ""
        except Exception as ex:
            return ToolResult(text=f"Error executing command: {ex}", is_error=True)

        if not timed_out and (len(stdout) + len(stderr)) > _MAX_BUFFER:
            output_truncated = True
            exit_code = -1
            # cap combined output at the boundary (stdout first, then stderr)
            if len(stdout) > _MAX_BUFFER:
                stdout, stderr = stdout[:_MAX_BUFFER], ""
            else:
                stderr = stderr[: _MAX_BUFFER - len(stdout)]

        parts: list[str] = []
        combined = (stdout + stderr).rstrip()
        if combined:
            parts.append(combined)
        if timed_out:
            parts.append(f"[timed out after {_TIMEOUT_S}s]")
        elif output_truncated:
            cap = _format_bytes(_MAX_BUFFER)
            parts.append(
                f"[Output truncated: command emitted >{cap} to stdout+stderr; "
                f"output cut at the {cap} boundary and the process was killed.\n"
                " To capture more: redirect to a file (e.g., "
                "`command > /tmp/out.log 2>&1`) and use read_file with "
                "offset/limit, or narrow via head/tail/grep in the command itself]"
            )
        elif exit_code != 0:
            parts.append(f"[exit code {exit_code}]")

        return ToolResult(
            text="\n".join(parts) or "(no output)",
            structured={
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "output_truncated": output_truncated,
            },
            is_error=(exit_code != 0 or timed_out or output_truncated),
        )


def build_bash_tool(policy: PathPolicy) -> list[Any]:
    return [BashTool(policy)]
