import os
from pathlib import Path
from typing import Any


class AppendFileTool:
    def __init__(self, working_directory: str | None = None):
        self._working_directory = working_directory

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return (
            "Append content to the end of a file. "
            "The file must already exist. "
            "Use this to write large files in stages — "
            "create the file with write_file first, then append additional sections."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to append to",
                },
                "content": {
                    "type": "string",
                    "description": "The content to append to the file",
                },
            },
            "required": ["path", "content"],
        }

    @property
    def is_mutating(self) -> bool:
        return True

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        path = tool_input.get("path")
        if isinstance(path, str) and path.strip():
            return [path]
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input["path"]
        content = tool_input["content"]
        try:
            if not os.path.isabs(path) and self._working_directory:
                path = os.path.join(self._working_directory, path)

            file_path = Path(path)
            if not file_path.exists():
                return f"Error: file does not exist: {path}. Use write_file to create it first."

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully appended to {path}"
        except Exception as ex:
            return f"Error appending to file: {ex}"
