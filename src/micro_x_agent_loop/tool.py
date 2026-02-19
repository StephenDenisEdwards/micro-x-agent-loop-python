from typing import Any, Protocol, runtime_checkable


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

    async def execute(self, tool_input: dict[str, Any]) -> str: ...
