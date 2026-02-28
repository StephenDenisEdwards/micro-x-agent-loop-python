from __future__ import annotations

from dataclasses import dataclass, field
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
