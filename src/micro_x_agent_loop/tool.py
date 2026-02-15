from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    async def execute(self, tool_input: dict[str, Any]) -> str: ...
