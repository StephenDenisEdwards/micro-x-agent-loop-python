import os
from typing import Any


class ReadFileTool:
    def __init__(self, working_directory: str | None = None):
        self._working_directory = working_directory

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file and return it as text. Supports plain text files and .docx documents."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read",
                },
            },
            "required": ["path"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        file_path = tool_input["path"]
        try:
            if not os.path.isabs(file_path) and self._working_directory:
                file_path = os.path.join(self._working_directory, file_path)

            if file_path.lower().endswith(".docx"):
                return self._extract_docx_text(file_path)

            with open(file_path, encoding="utf-8") as f:
                return f.read()

        except Exception as ex:
            return f"Error reading file: {ex}"

    @staticmethod
    def _extract_docx_text(file_path: str) -> str:
        from docx import Document

        doc = Document(file_path)
        return os.linesep.join(p.text for p in doc.paragraphs)
