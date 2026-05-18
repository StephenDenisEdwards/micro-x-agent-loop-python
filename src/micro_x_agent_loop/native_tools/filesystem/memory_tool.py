"""F5 — native save_memory tool. Faithful port of the TS filesystem
save-memory tool (ADR-025).

Not PathPolicy-bound: it is configured with the user-memory directory and
the MEMORY.md auto-load line cap (injected; sourced from config at F6).
Preserves: .md-only validation, plain-filename / no-traversal rejection,
mkdir -p of the memory dir, the MEMORY.md line-count warning (trailing
newline does not count as an extra line), and the exact messages.

is_mutating=False — matches the TS destructiveHint:false and the current
MCP proxy default; memory writes are outside the workspace checkpoint set.
"""

from __future__ import annotations

import os
from typing import Any

from micro_x_agent_loop.tool import ToolResult


class SaveMemoryTool:
    def __init__(self, memory_dir: str, max_lines: int) -> None:
        self._memory_dir = memory_dir
        self._max_lines = max_lines

    @property
    def name(self) -> str:
        return "filesystem__save_memory"

    @property
    def description(self) -> str:
        return (
            "Save persistent memory loaded in future sessions. Files live in "
            f"the user memory directory. Use MEMORY.md as the index (first "
            f"{self._max_lines} lines auto-loaded); put detail in topic files "
            "and link them from MEMORY.md."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["file", "content"],
            "additionalProperties": False,
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        file = tool_input.get("file", "")
        content = tool_input.get("content", "")
        try:
            if not file.endswith(".md"):
                return ToolResult(
                    text="Error: Only .md files are allowed in the memory directory.",
                    is_error=True,
                )
            if "/" in file or "\\" in file or ".." in file:
                return ToolResult(
                    text="Error: 'file' must be a plain filename "
                    "(no path separators or '..').",
                    is_error=True,
                )

            os.makedirs(self._memory_dir, exist_ok=True)
            target = os.path.join(self._memory_dir, file)
            with open(target, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)

            message = f"Successfully saved {file}"
            structured: dict[str, Any] = {
                "success": True,
                "file": file,
                "message": f"Successfully saved {file}",
            }

            if file == "MEMORY.md":
                line_count = content.split("\n")
                count = len(line_count)
                if content.endswith("\n"):
                    count -= 1  # trailing newline is not an extra line
                structured["line_count"] = count
                if count > self._max_lines:
                    warning = (
                        f"MEMORY.md is {count} lines but only the first "
                        f"{self._max_lines} lines are loaded into context. "
                        "Consider moving detailed content to topic files and "
                        "linking from MEMORY.md."
                    )
                    structured["warning"] = warning
                    message += f"\n\nWarning: {warning}"

            return ToolResult(text=message, structured=structured)
        except Exception as ex:
            return ToolResult(text=f"Error: {ex}", is_error=True)


def build_save_memory_tool(memory_dir: str, max_lines: int) -> list[Any]:
    return [SaveMemoryTool(memory_dir, max_lines)]
