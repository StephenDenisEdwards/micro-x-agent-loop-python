from __future__ import annotations

from pathlib import Path
from typing import Any


class SaveMemoryTool:
    """Write files within the user memory directory.

    Sandboxed: only allows writes to ``.md`` files inside the configured
    memory directory.  After writing ``MEMORY.md`` the tool checks the
    line count and appends a warning if the file exceeds *max_lines*.
    """

    def __init__(self, memory_dir: str, max_lines: int = 200) -> None:
        self._memory_dir = Path(memory_dir)
        self._max_lines = max_lines

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return (
            "Save persistent memory that will be loaded in future sessions. "
            "Files are stored in the user memory directory. "
            "Use MEMORY.md as the main index (first {max_lines} lines loaded automatically). "
            "Create topic files for detailed notes and reference them from MEMORY.md."
        ).format(max_lines=self._max_lines)

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": (
                        "Filename within the memory directory "
                        "(e.g. 'MEMORY.md', 'patterns.md'). Must end with .md."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write.",
                },
            },
            "required": ["file", "content"],
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        file_name = tool_input.get("file", "")
        content = tool_input.get("content", "")

        if not file_name or not isinstance(file_name, str):
            return "Error: 'file' parameter is required and must be a string."

        if not file_name.endswith(".md"):
            return "Error: only .md files are allowed in the memory directory."

        # Prevent path traversal
        if "/" in file_name or "\\" in file_name or ".." in file_name:
            return "Error: 'file' must be a plain filename (no path separators or '..')."

        target = self._memory_dir / file_name

        try:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except Exception as ex:
            return f"Error writing memory file: {ex}"

        result = f"Successfully saved {file_name}"

        # Line-count warning for MEMORY.md
        if file_name == "MEMORY.md":
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            if line_count > self._max_lines:
                result += (
                    f"\n\nWarning: MEMORY.md is {line_count} lines but only the first "
                    f"{self._max_lines} lines are loaded into context. "
                    "Consider moving detailed content to topic files and linking from MEMORY.md."
                )

        return result
