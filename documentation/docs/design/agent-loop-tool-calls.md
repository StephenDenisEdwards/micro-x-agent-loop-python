# Agent Loop Tool Calls (Built-in + MCP)

This document explains how the agent loop discovers tools, decides to call them, executes them, and returns results to the model. It covers both built-in tools and MCP (Model Context Protocol) tools, with code snippets from this repository.

## Overview

A single user turn flows through these stages:

1. The agent sends the conversation and tool schema to the provider.
2. The provider returns streamed assistant content plus optional `tool_use` blocks.
3. The turn engine executes each tool call in parallel.
4. Tool results are injected back into the conversation as `tool_result` blocks.
5. The loop repeats until the provider returns no more tool calls.

The same execution path is used for built-in tools and MCP tools because MCP tools are wrapped to conform to the `Tool` protocol.

## Tool Call Loop (Turn Engine)

The loop lives in `src/micro_x_agent_loop/turn_engine.py`. The provider returns tool calls in `tool_use_blocks`, then the engine executes them and appends results back into the conversation.

```python
# src/micro_x_agent_loop/turn_engine.py
async def run(self, *, messages: list[dict], user_message: str) -> tuple[str | None, str | None]:
    last_assistant_message_id: str | None = None
    current_user_message_id = self._on_append_message("user", user_message)
    self._on_user_message_appended(current_user_message_id)
    await self._on_maybe_compact()

    max_tokens_attempts = 0

    while True:
        message, tool_use_blocks, stop_reason = await self._provider.stream_chat(
            self._model,
            self._max_tokens,
            self._temperature,
            self._system_prompt,
            messages,
            self._converted_tools,
            line_prefix=self._line_prefix,
        )

        last_assistant_message_id = self._on_append_message("assistant", message["content"])

        if stop_reason == "max_tokens" and not tool_use_blocks:
            ...

        if not tool_use_blocks:
            return current_user_message_id, last_assistant_message_id

        self._on_ensure_checkpoint_for_turn(tool_use_blocks)
        tool_results = await self.execute_tools(
            tool_use_blocks,
            last_assistant_message_id=last_assistant_message_id,
        )
        self._on_append_message("user", tool_results)
        await self._on_maybe_compact()
        print()
```

## Executing Tool Calls (Parallel)

Each `tool_use` block is dispatched to the matching `Tool` instance from the registry or MCP, with parallel execution via `asyncio.gather`.

```python
# src/micro_x_agent_loop/turn_engine.py
async def execute_tools(self, tool_use_blocks: list[dict], *, last_assistant_message_id: str | None) -> list[dict]:
    async def run_one(block: dict) -> dict:
        tool_name = block["name"]
        tool_use_id = block["id"]
        tool = self._tool_map.get(tool_name)
        tool_input = block["input"]

        self._on_tool_started(tool_use_id, tool_name)

        if tool is None:
            content = f'Error: unknown tool "{tool_name}"'
            ...
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": True}

        try:
            self._on_maybe_track_mutation(tool_name, tool, tool_input)
            result = await tool.execute(tool_input)
            result = self._truncate_tool_result(result, tool_name)
            ...
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}
        except Exception as ex:
            content = f'Error executing tool "{tool_name}": {ex}'
            ...
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": True}

    return list(await asyncio.gather(*(run_one(b) for b in tool_use_blocks)))
```

## Where Tools Come From

Tool discovery happens during bootstrap in `src/micro_x_agent_loop/bootstrap.py`.

1. Built-in tools are loaded via `get_all(...)`.
2. MCP tools are connected and appended when `McpServers` is configured.

```python
# src/micro_x_agent_loop/bootstrap.py
tools = get_all(
    app.working_directory,
    env.google_client_id,
    env.google_client_secret,
    env.anthropic_admin_api_key,
    env.brave_api_key,
    env.github_token,
)

mcp_manager: McpManager | None = None
mcp_tools: list = []
if app.mcp_server_configs:
    mcp_manager = McpManager(app.mcp_server_configs)
    mcp_tools = await mcp_manager.connect_all()
    tools.extend(mcp_tools)
```

## MCP Server Connections

`McpManager` connects to each MCP server (stdio or HTTP), initializes a session, and lists available tools. Each MCP tool is wrapped as a `McpToolProxy` that implements the normal tool interface.

```python
# src/micro_x_agent_loop/mcp/mcp_manager.py
async def connect_all(self) -> list[Tool]:
    all_tools: list[Tool] = []

    for server_name, config in self._server_configs.items():
        conn = _ServerConnection(server_name)
        self._connections.append(conn)

        try:
            await conn.start(config)
            await conn.wait_ready()
            all_tools.extend(conn.tools)
            logger.info(f"MCP server '{server_name}': {len(conn.tools)} tool(s) discovered")
        except Exception as ex:
            logger.error(f"Failed to connect to MCP server '{server_name}': {ex}")

    return all_tools
```

## MCP Tool Adapter (McpToolProxy)

`McpToolProxy` exposes MCP tools through the same `execute(...)` method used by built-in tools. This is why the main tool execution path does not need MCP-specific logic.

```python
# src/micro_x_agent_loop/mcp/mcp_tool_proxy.py
class McpToolProxy:
    def __init__(self, server_name: str, tool_name: str, tool_description: str | None, tool_input_schema: dict[str, Any], session: ClientSession):
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = tool_description or ""
        self._input_schema = tool_input_schema
        self._session = session

    @property
    def name(self) -> str:
        return f"{self._server_name}__{self._tool_name}"

    async def execute(self, tool_input: dict[str, Any]) -> str:
        result = await self._session.call_tool(self._tool_name, arguments=tool_input)
        text_parts = [block.text for block in result.content if isinstance(block, TextContent)]
        output = "\n".join(text_parts) if text_parts else "(no output)"
        if result.isError:
            raise RuntimeError(output)
        return output
```

## Summary

The agent loop uses a single tool execution path for both built-in and MCP tools. MCP servers are connected at startup, their tools are wrapped in `McpToolProxy`, and those proxies are merged into the same tool map. During each turn, the provider returns `tool_use` blocks, the turn engine executes them in parallel via `Tool.execute(...)`, and results are appended back into the conversation.

**Note:** All tool results — both built-in and MCP — are returned as unstructured text strings. For MCP tools, this is inherent to the protocol (`TextContent` blocks). This design works for prompt mode (the LLM interprets text naturally) but constrains compiled mode, where generated code needs structured data for programmatic processing. See [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md).
