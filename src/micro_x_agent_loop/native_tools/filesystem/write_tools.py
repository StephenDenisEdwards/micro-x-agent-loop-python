"""F3 — native mutating filesystem tools: write_file, append_file,
edit_file, delete_file. Faithful port of the TS tools.

All are is_mutating=True (the agent's checkpoint-for-turn logic keys off
that). predict_touched_paths returns [] — matching the current MCP proxy
behaviour exactly (a deliberate faithful-port decision; implementing it
properly is a separate later improvement, not bundled into this port).

Preserves: require_writable (readonly-root rejection), parent-dir
creation, append's "use write_file first" message, delete's directory
refusal, and edit_file's exact-string + EOL-detection/normalisation +
UTF-8 BOM preservation + size/binary guards + atomic temp-then-rename.
"""

from __future__ import annotations

import os
import stat
import tempfile
from typing import Any

from micro_x_agent_loop.native_tools.filesystem.paths import (
    PathPolicy,
    require_writable,
    resolve_allowed,
)
from micro_x_agent_loop.tool import ToolResult

_BINARY_SNIFF_BYTES = 8 * 1024
_DEFAULT_EDIT_MAX_BYTES = 5 * 1024 * 1024
_EOL_SAMPLE_BYTES = 64 * 1024
_BOM = b"\xef\xbb\xbf"
_NO_INPUT_EXTRA = {"additionalProperties": False}


def _is_binary(buf: bytes) -> bool:
    return 0 in buf[:_BINARY_SNIFF_BYTES]


def _err(text: str) -> ToolResult:
    return ToolResult(text=text, is_error=True)


class _MutatingBase:
    def __init__(self, policy: PathPolicy) -> None:
        self._policy = policy

    @property
    def is_mutating(self) -> bool:
        return True

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []  # faithful to current MCP proxy; see module docstring


class WriteFileTool(_MutatingBase):
    @property
    def name(self) -> str:
        return "filesystem__write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file, creating it if it doesn't exist. Parent "
            "directories are created automatically. Path must be inside the allowed roots."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            **_NO_INPUT_EXTRA,
        }

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            resolved = resolve_allowed(self._policy, tool_input.get("path"), must_exist=False)
            require_writable(self._policy, resolved)
            content = tool_input["content"]
            os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
            with open(resolved, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            return ToolResult(
                text=f"Successfully wrote to {resolved}",
                structured={
                    "success": True,
                    "path": resolved,
                    "size_bytes": len(content.encode("utf-8")),
                },
            )
        except Exception as ex:
            return _err(f"Error writing file: {ex}")


class AppendFileTool(_MutatingBase):
    @property
    def name(self) -> str:
        return "filesystem__append_file"

    @property
    def description(self) -> str:
        return (
            "Append content to the end of a file. The file must already exist "
            "(create it with write_file first). Path must be inside the allowed roots."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            **_NO_INPUT_EXTRA,
        }

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            resolved = resolve_allowed(self._policy, tool_input.get("path"), must_exist=False)
            require_writable(self._policy, resolved)
            if not os.path.exists(resolved):
                return _err(
                    f"Error: file does not exist: {resolved}. "
                    f"Use write_file to create it first."
                )
            content = tool_input["content"]
            with open(resolved, "a", encoding="utf-8", newline="") as fh:
                fh.write(content)
            return ToolResult(
                text=f"Successfully appended to {resolved}",
                structured={
                    "success": True,
                    "path": resolved,
                    "appended_bytes": len(content.encode("utf-8")),
                },
            )
        except Exception as ex:
            return _err(f"Error appending to file: {ex}")


class DeleteFileTool(_MutatingBase):
    @property
    def name(self) -> str:
        return "filesystem__delete_file"

    @property
    def description(self) -> str:
        return (
            "Delete a single file. Refuses directories — use bash for recursive/bulk "
            "deletion. Checkpointed before deletion so /rewind can restore it. Path "
            "must be inside the allowed roots."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            **_NO_INPUT_EXTRA,
        }

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            resolved = resolve_allowed(self._policy, tool_input.get("path"), must_exist=False)
            require_writable(self._policy, resolved)
            if not os.path.exists(resolved):
                return _err(f"file not found: {resolved}")
            if os.path.isdir(resolved):
                return _err(
                    f"refusing to delete directory: {resolved} — use bash "
                    f"(rm -r / rmdir) for directory removal"
                )
            if not os.path.isfile(resolved):
                return _err(f"not a regular file: {resolved}")
            size = os.stat(resolved).st_size
            os.unlink(resolved)
            return ToolResult(
                text=f"deleted {resolved} ({size} bytes)",
                structured={"path": resolved, "deleted": True, "size_bytes": size},
            )
        except Exception as ex:
            return _err(f"Error deleting file: {ex}")


def _detect_eol(text: str) -> str:
    sample = text[:_EOL_SAMPLE_BYTES]
    return "\r\n" if "\r\n" in sample else "\n"


def _normalise_eol(s: str, target: str) -> str:
    lf = s.replace("\r\n", "\n").replace("\r", "\n")
    return lf if target == "\n" else lf.replace("\n", "\r\n")


def _atomic_write(file_path: str, data: bytes, mode_bits: int) -> None:
    d = os.path.dirname(file_path) or "."
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(file_path)}.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, mode_bits)
        except OSError:
            pass
        os.replace(tmp, file_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _edit_max_bytes() -> int:
    raw = os.environ.get("FILESYSTEM_EDIT_MAX_BYTES")
    if not raw:
        return _DEFAULT_EDIT_MAX_BYTES
    try:
        n = int(raw)
        return n if n > 0 else _DEFAULT_EDIT_MAX_BYTES
    except ValueError:
        return _DEFAULT_EDIT_MAX_BYTES


class EditFileTool(_MutatingBase):
    @property
    def name(self) -> str:
        return "filesystem__edit_file"

    @property
    def description(self) -> str:
        return (
            "Surgical exact-string edit to an existing file. old_string must be "
            "unique (or set replace_all=true). CRLF/LF detected and normalised; "
            "UTF-8 BOM preserved. Binary refused; >5 MB refused "
            "(FILESYSTEM_EDIT_MAX_BYTES)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_string", "new_string"],
            **_NO_INPUT_EXTRA,
        }

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        old = tool_input["old_string"]
        new = tool_input["new_string"]
        replace_all = bool(tool_input.get("replace_all", False))
        try:
            if old == "":
                return _err("old_string is empty — provide the exact text to replace")
            if old == new:
                return _err("old_string and new_string are identical — refusing no-op")

            resolved = resolve_allowed(self._policy, tool_input.get("path"), must_exist=False)
            require_writable(self._policy, resolved)

            if not os.path.exists(resolved):
                return _err(f"file not found: {resolved}")
            st = os.stat(resolved)
            if not os.path.isfile(resolved):
                return _err(f"not a regular file: {resolved}")
            max_bytes = _edit_max_bytes()
            if st.st_size > max_bytes:
                return _err(
                    f"file too large for edit_file ({st.st_size} bytes > "
                    f"{max_bytes}) — use write_file or split the edit"
                )

            with open(resolved, "rb") as fh:
                buf = fh.read()
            if _is_binary(buf):
                return _err(
                    f"refusing to edit binary file: {resolved} (null byte "
                    f"detected in first {_BINARY_SNIFF_BYTES} bytes)"
                )

            has_bom = buf[:3] == _BOM
            text = buf[3:].decode("utf-8") if has_bom else buf.decode("utf-8")

            eol = _detect_eol(text)
            old_n = _normalise_eol(old, eol)
            new_n = _normalise_eol(new, eol)

            count = text.count(old_n)
            if count == 0:
                return _err(f"old_string not found in {resolved}")
            if count > 1 and not replace_all:
                return _err(
                    f"old_string is not unique ({count} matches) in {resolved} "
                    f"— add surrounding context or set replace_all=true"
                )

            if replace_all:
                updated = text.replace(old_n, new_n)
                replacements = count
            else:
                idx = text.index(old_n)
                updated = text[:idx] + new_n + text[idx + len(old_n):]
                replacements = 1

            out = (_BOM + updated.encode("utf-8")) if has_bom else updated.encode("utf-8")
            _atomic_write(resolved, out, stat.S_IMODE(st.st_mode))

            tail = "" if replacements == 1 else "s"
            return ToolResult(
                text=f"edited {resolved}: {replacements} replacement{tail}",
                structured={"path": resolved, "replacements": replacements},
            )
        except Exception as ex:
            return _err(f"Error editing file: {ex}")


def build_write_tools(policy: PathPolicy) -> list[Any]:
    return [
        WriteFileTool(policy),
        AppendFileTool(policy),
        EditFileTool(policy),
        DeleteFileTool(policy),
    ]
