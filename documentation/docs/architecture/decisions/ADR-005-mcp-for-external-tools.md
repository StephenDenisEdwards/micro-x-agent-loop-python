# ADR-005: MCP for External Tool Integration

## Status

Accepted

## Context

The agent has a fixed set of built-in tools registered via `tool_registry.py`. Adding new tools requires writing Python code, implementing the `Tool` Protocol, and modifying the registry. This limits extensibility — the agent can only do what its built-in tools allow.

The **Model Context Protocol (MCP)** is an open standard that enables LLM applications to connect to external tool servers via a standardized interface. A growing ecosystem of MCP servers already exists (filesystem, databases, web APIs, etc.), and many tools can be used out of the box without writing any agent-specific code.

Options considered:

1. **Continue with built-in tools only** — each new capability requires a new Python tool class
2. **Custom plugin system** — define our own plugin format for loading external tools
3. **MCP integration** — use the official `mcp` Python SDK to connect to any MCP-compatible server

## Decision

Integrate MCP using the official `mcp` Python SDK. MCP servers are configured in `config.json` under the `McpServers` key. The agent supports both **stdio** (local process) and **StreamableHTTP** (remote endpoint) transports.

MCP tools are wrapped in a `McpToolProxy` adapter class that satisfies the existing `Tool` Protocol. Tool names are prefixed as `{server_name}__{tool_name}` to avoid collisions with built-in tools. The proxy delegates `execute()` to the MCP session's `call_tool()` method.

A `McpManager` class manages all server connections using `AsyncExitStack` for lifecycle management. At startup, it connects to all configured servers, discovers their tools, and returns them for merging with built-in tools. At shutdown, it cleanly closes all connections.

The agent itself requires **zero changes** — it already dispatches tools by name via `_tool_map` and works with any object satisfying the `Tool` Protocol.

## Consequences

**Easier:**

- Any MCP-compatible server can be added via config — no code changes needed
- Access to the growing MCP ecosystem (filesystem, database, API tools, etc.)
- Both local (stdio) and remote (HTTP) servers are supported
- Built-in tools and MCP tools coexist seamlessly
- Tool Protocol abstraction validated — new tool sources integrate without touching the agent

**Harder:**

- New runtime dependency (`mcp>=1.0.0`) with its own transitive dependencies
- MCP server failures at startup are logged but don't block the agent — users must check logs to notice connection failures
- MCP tool names are prefixed (`server__tool`), which may be less intuitive for the LLM than short built-in names
- Subprocess lifecycle management (stdio servers) adds complexity to shutdown
