from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolResult:
    text: str
    structured: dict[str, Any] | None = None
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    @property
    def is_mutating(self) -> bool: ...

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]: ...

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult: ...


def _sort_schema(value: Any) -> Any:
    """Recursively sort dict keys and preserve list order for deterministic serialisation."""
    if isinstance(value, dict):
        return {k: _sort_schema(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_sort_schema(item) for item in value]
    return value


def normalize_tool_content(content: str | list) -> str:
    """Normalize tool_result content to a plain string.

    Tool result content may be a string or a list of typed blocks
    (e.g. ``[{"type": "text", "text": "..."}]``). This function
    extracts and joins the text from list-form content.
    """
    if isinstance(content, list):
        return "\n".join(
            sub.get("text", "")
            for sub in content
            if isinstance(sub, dict) and sub.get("type") == "text"
        )
    return str(content)


def canonicalise_tools(tools: list[Tool]) -> list[dict]:
    """Produce a deterministic, stable tool list for the API.

    Sorts tools by name and recursively sorts schema keys to ensure
    byte-identical serialisation across calls.
    """
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": _sort_schema(t.input_schema),
        }
        for t in sorted(tools, key=lambda t: t.name)
    ]
