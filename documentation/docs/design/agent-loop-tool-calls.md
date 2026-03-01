# Agent Loop Tool Calls

This document explains how the agent loop discovers tools, decides to call them, executes them, and returns results to the model. All tools are MCP (Model Context Protocol) servers — there are no built-in Python tool implementations.

## Overview

A single user turn flows through these stages:

1. The agent sends the conversation and tool schema to the provider.
2. The provider returns streamed assistant content plus optional `tool_use` blocks.
3. The turn engine executes each tool call in parallel.
4. Tool results are formatted via `ToolResultFormatter` and injected back into the conversation as `tool_result` blocks.
5. The loop repeats until the provider returns no more tool calls.

All tools are `McpToolProxy` instances that conform to the `Tool` protocol — the turn engine has no MCP-specific logic.

## Tool Call Loop (Turn Engine)

The loop lives in `src/micro_x_agent_loop/turn_engine.py`. The provider returns tool calls in `tool_use_blocks`, then the engine executes them and appends results back into the conversation.

```python
# src/micro_x_agent_loop/turn_engine.py
async def run(self, *, messages: list[dict], user_message: str) -> tuple[str | None, str | None]:
    last_assistant_message_id: str | None = None
    current_user_message_id = self._events.on_append_message("user", user_message)
    self._events.on_user_message_appended(current_user_message_id)
    await self._events.on_maybe_compact()

    max_tokens_attempts = 0

    while True:
        # Resolve {current_date} in the system prompt template on each iteration,
        # so the date stays accurate across midnight boundaries.
        system_prompt = resolve_system_prompt(self._system_prompt_template)

        message, tool_use_blocks, stop_reason, usage = await self._provider.stream_chat(
            self._model,
            self._max_tokens,
            self._temperature,
            system_prompt,
            messages,
            self._converted_tools,
            line_prefix=self._line_prefix,
        )

        self._events.on_api_call_completed(usage, "main")

        # Record full request/response payload to the in-memory ring buffer
        # and log to api_payloads.jsonl (if the api_payload LogConsumer is configured).
        if self._api_payload_store is not None:
            self._record_api_payload(system_prompt, messages, message, stop_reason, usage)

        last_assistant_message_id = self._events.on_append_message("assistant", message["content"])

        if stop_reason == "max_tokens" and not tool_use_blocks:
            ...

        if not tool_use_blocks:
            return current_user_message_id, last_assistant_message_id

        self._events.on_ensure_checkpoint_for_turn(tool_use_blocks)
        tool_results = await self.execute_tools(
            tool_use_blocks,
            last_assistant_message_id=last_assistant_message_id,
        )
        self._events.on_append_message("user", tool_results)
        await self._events.on_maybe_compact()
        print()
```

## Executing Tool Calls (Parallel)

Each `tool_use` block is dispatched to the matching `McpToolProxy` instance, with parallel execution via `asyncio.gather`. Tool results are formatted via `ToolResultFormatter` before entering the context window.

```python
# src/micro_x_agent_loop/turn_engine.py
async def execute_tools(self, tool_use_blocks: list[dict], *, last_assistant_message_id: str | None) -> list[dict]:
    async def run_one(block: dict) -> dict:
        tool_name = block["name"]
        tool_use_id = block["id"]
        tool = self._tool_map.get(tool_name)
        tool_input = block["input"]

        if tool is None:
            content = f'Error: unknown tool "{tool_name}"'
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": True}

        try:
            self._on_maybe_track_mutation(tool_name, tool, tool_input)
            tool_result = await tool.execute(tool_input)
            if tool_result.is_error:
                raise RuntimeError(tool_result.text)
            formatted = self._formatter.format(tool_name, tool_result.text, tool_result.structured)
            result_text = self._truncate_tool_result(formatted, tool_name)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result_text}
        except Exception as ex:
            content = f'Error executing tool "{tool_name}": {ex}'
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": True}

    return list(await asyncio.gather(*(run_one(b) for b in tool_use_blocks)))
```

## Where Tools Come From

Tool discovery happens during bootstrap in `src/micro_x_agent_loop/bootstrap.py`. All tools come from MCP servers — there is no `tool_registry`.

```python
# src/micro_x_agent_loop/bootstrap.py
mcp_manager: McpManager | None = None
tools: list = []
if app.mcp_server_configs:
    mcp_manager = McpManager(app.mcp_server_configs)
    tools = await mcp_manager.connect_all()
```

## MCP Server Connections

`McpManager` connects to all configured MCP servers **concurrently** (stdio or HTTP), initializes sessions, and lists available tools. Each MCP tool is wrapped as a `McpToolProxy` that implements the `Tool` protocol.

```python
# src/micro_x_agent_loop/mcp/mcp_manager.py
async def connect_all(self) -> list[Tool]:
    all_tools: list[Tool] = []
    connections: list[_ServerConnection] = []

    # Start all servers concurrently
    for server_name, config in self._server_configs.items():
        conn = _ServerConnection(server_name)
        connections.append(conn)
        await conn.start(config)  # non-blocking, creates task

    # Then await readiness
    for conn in connections:
        try:
            await conn.wait_ready()
            all_tools.extend(conn.tools)
        except Exception as ex:
            logger.error(f"Failed to connect to MCP server '{conn.name}': {ex}")

    return all_tools
```

## MCP Tool Adapter (McpToolProxy)

`McpToolProxy` exposes MCP tools through the same `execute(...)` method, returning a `ToolResult` with both text and optional structured data. This is why the main tool execution path has no MCP-specific logic.

```python
# src/micro_x_agent_loop/mcp/mcp_tool_proxy.py
class McpToolProxy:
    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str | None,
        tool_input_schema: dict[str, Any],
        session: ClientSession,
        *,
        is_mutating: bool = False,
        output_schema: dict[str, Any] | None = None,
    ): ...

    @property
    def name(self) -> str:
        return f"{self._server_name}__{self._tool_name}"

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        result = await self._session.call_tool(self._tool_name, arguments=tool_input)
        text_parts = [block.text for block in result.content if isinstance(block, TextContent)]
        output = "\n".join(text_parts) if text_parts else "(no output)"

        structured: dict[str, Any] | None = None
        if hasattr(result, "structuredContent") and result.structuredContent is not None:
            structured = dict(result.structuredContent)

        if result.isError:
            return ToolResult(text=output, structured=structured, is_error=True)
        return ToolResult(text=output, structured=structured)
```

## Tool Result Formatting

Before tool results enter the LLM context window, `ToolResultFormatter` converts `ToolResult.structured` into optimised text using per-tool config from `ToolFormatting`:

- `text` — extract a single field (e.g., `stdout` from bash)
- `table` — markdown table for arrays of objects (e.g., search results)
- `key_value` — simple `key: value` lines
- `json` — pretty-printed JSON (default)

When no `structuredContent` is present, the formatter falls back to `ToolResult.text`.

## Summary

The agent loop uses a single tool execution path for all tools. MCP servers are connected in parallel at startup, their tools are wrapped in `McpToolProxy`, and those proxies populate the tool map. During each turn, the provider returns `tool_use` blocks, the turn engine executes them in parallel via `Tool.execute(...)`, formats the results via `ToolResultFormatter`, and appends them back into the conversation.

Tool results carry both structured JSON (`structuredContent`) and plain text (`TextContent`). The `ToolResultFormatter` uses the structured data when available for optimal formatting, falling back to plain text otherwise. See [ADR-015](../architecture/decisions/ADR-015-all-tools-as-typescript-mcp-servers.md) for the migration decision.
