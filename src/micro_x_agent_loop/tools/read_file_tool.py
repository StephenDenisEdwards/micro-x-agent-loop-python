import os
from pathlib import Path
from typing import Any


class ReadFileTool:
    def __init__(self, documents_directory: str | None = None, working_directory: str | None = None):
        self._documents_directory = documents_directory
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
            # Resolve relative paths against the configured working directory
            if not os.path.isabs(file_path) and self._working_directory:
                candidate = os.path.join(self._working_directory, file_path)
                if os.path.exists(candidate):
                    file_path = candidate

            if not os.path.isabs(file_path) and not os.path.exists(file_path):
                resolved = self._resolve_relative_path(file_path)
                if resolved:
                    file_path = resolved

            if file_path.lower().endswith(".docx"):
                return self._extract_docx_text(file_path)

            with open(file_path, encoding="utf-8") as f:
                return f.read()

        except Exception as ex:
            return f"Error reading file: {ex}"

    def _resolve_relative_path(self, relative_path: str) -> str | None:
        """Walk up from CWD to repo root, trying to resolve a relative path at each level.
        Falls back to the configured documents directory if set."""
        current = Path.cwd()
        while True:
            candidate = current / relative_path
            if candidate.exists():
                return str(candidate)

            # Stop at repo root
            if (current / ".git").exists():
                break

            parent = current.parent
            if parent == current:
                break
            current = parent

        # Try the configured documents directory as a fallback
        if self._documents_directory:
            docs_base = Path(self._documents_directory)
            if not docs_base.is_absolute():
                docs_base = Path.cwd() / docs_base

            candidate = docs_base / relative_path
            if candidate.exists():
                return str(candidate)

            # Also try just the filename
            filename = Path(relative_path).name
            candidate = docs_base / filename
            if candidate.exists():
                return str(candidate)

        return None

    @staticmethod
    def _extract_docx_text(file_path: str) -> str:
        from docx import Document

        doc = Document(file_path)
        return os.linesep.join(p.text for p in doc.paragraphs)
