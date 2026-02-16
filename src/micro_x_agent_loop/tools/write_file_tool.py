from pathlib import Path
from typing import Any


class WriteFileTool:
    def __init__(self, working_directory: str | None = None):
        self._working_directory = working_directory

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file, creating it if it doesn't exist."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input["path"]
        content = tool_input["content"]
        try:
            file_path = Path(path)
            if not file_path.is_absolute() and self._working_directory:
                file_path = Path(self._working_directory) / file_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote to {path}"
        except Exception as ex:
            return f"Error writing file: {ex}"
