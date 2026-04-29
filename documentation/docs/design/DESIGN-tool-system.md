# Design: Tool System

## Overview

The tool system provides the LLM with the ability to interact with the outside world. All tools are implemented as **TypeScript MCP (Model Context Protocol) servers** that communicate with the Python agent loop over stdio. Each tool accepts a JSON input, performs an action, and returns a `ToolResult` containing both text and optional structured data.

See [ADR-015](../architecture/decisions/ADR-015-all-tools-as-typescript-mcp-servers.md) for the architectural decision behind the migration from built-in Python tools to TypeScript MCP servers.

## Tool Protocol

```python
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
```

| Member | Purpose |
|--------|---------|
| `name` | Unique identifier sent to the LLM (e.g., `"filesystem__read_file"`) |
| `description` | Natural-language description the LLM uses to decide when to call the tool |
| `input_schema` | JSON Schema dict defining the expected input parameters |
| `is_mutating` | Whether the tool modifies files (used by checkpoint tracking); derived from MCP `destructiveHint` annotation |
| `predict_touched_paths` | Returns predicted file paths the tool will modify (used for pre-mutation snapshots) |
| `execute` | Executes the tool and returns a `ToolResult` |

Using `typing.Protocol` provides structural typing — any class with matching properties and methods satisfies the interface without explicit inheritance. All tools are `McpToolProxy` instances at runtime.

### ToolResult

`ToolResult` carries both human-readable text and machine-parseable structured data:

| Field | Type | Purpose |
|-------|------|---------|
| `text` | `str` | Plain text extracted from MCP `TextContent` blocks — used as fallback for the LLM context window |
| `structured` | `dict \| None` | JSON data from MCP `structuredContent` — used by `ToolResultFormatter` for optimised formatting |
| `is_error` | `bool` | Whether the tool execution failed |

### Mutation Metadata

Tools that modify files declare mutation intent via MCP annotations. `McpToolProxy` reads the `destructiveHint` annotation to set `is_mutating`. When file checkpointing is enabled, the agent snapshots files before mutation so they can be restored via `/rewind`.

Currently tracked mutations:

| Tool | Strategy | Notes |
|------|----------|-------|
| `filesystem__write_file` | Strict | Returns `[path]` from tool input |
| `filesystem__append_file` | Strict | Returns `[path]` from tool input |
| `filesystem__bash` | Best-effort | Parses the shell command to extract likely mutated paths via `bash_command_parser.extract_mutated_paths()` (Python client-side) |

By default (`CheckpointWriteToolsOnly=true`), only `write_file` and `append_file` are tracked. Set `CheckpointWriteToolsOnly=false` to also track bash mutations.

See [Memory System Design](DESIGN-memory-system.md) for the full checkpoint lifecycle and bash parser details.

## Tool Discovery

All tools come from MCP servers. At startup, `bootstrap.py` creates an `McpManager` which connects to all configured servers in parallel, discovers their tools, and wraps each in a `McpToolProxy`.

```python
# src/micro_x_agent_loop/bootstrap.py
mcp_manager: McpManager | None = None
tools: list = []
if app.mcp_server_configs:
    mcp_manager = McpManager(app.mcp_server_configs)
    tools = await mcp_manager.connect_all()
```

There is no `tool_registry` — tool availability is determined entirely by which MCP servers are configured in `config.json` under `McpServers`. Credentials flow to servers via `env` blocks in the server config.

## MCP Servers

Most first-party tools are implemented as TypeScript MCP servers in `mcp_servers/ts/`, organised as an npm workspaces monorepo. The `codegen` server is a Python FastMCP server in `mcp_servers/python/codegen/`.

### Server Grouping

| Server | Tools | Key Credential |
|--------|-------|----------------|
| `filesystem` | bash, read_file, write_file, append_file, save_memory | `FILESYSTEM_WORKING_DIR`, `USER_MEMORY_DIR` |
| `web` | web_fetch, web_search | `BRAVE_API_KEY` |
| `linkedin` | linkedin_jobs, linkedin_job_detail | _(scraping)_ |
| `github` | list_prs, get_pr, create_pr, list_issues, create_issue, get_file, search_code, list_repos | `GITHUB_TOKEN` |
| `google` | gmail_search, gmail_read, gmail_send, calendar_list_events, calendar_create_event, calendar_get_event, contacts_search, contacts_list, contacts_get, contacts_create, contacts_update, contacts_delete | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| `anthropic-admin` | anthropic_usage | `ANTHROPIC_ADMIN_API_KEY` |
| `interview-assist` | ia_healthcheck, ia_list_recordings, ia_analyze_session, ia_evaluate_session, ia_compare_strategies, ia_tune_threshold, ia_regression_test, ia_create_baseline, ia_transcribe_once, stt_list_devices, stt_start_session, stt_get_updates, stt_get_session, stt_stop_session | `INTERVIEW_ASSIST_REPO` |
| `codegen` | generate_code | `ANTHROPIC_API_KEY`, `PROJECT_ROOT`, `WORKING_DIR` |

Each tool has its own detailed documentation in the [tools/](tools/) directory.

### Project Structure

```
mcp_servers/ts/
  package.json                    # npm workspaces root
  tsconfig.base.json
  packages/
    shared/                       # @micro-x-ai/mcp-shared
      src/
        validation.ts             # Zod input/output validation
        logging.ts                # Structured JSON stderr logger
        errors.ts                 # ValidationError, UpstreamError, PermissionError
        server-factory.ts         # stdio/HTTP transport factory
    filesystem/                   # @micro-x-ai/mcp-filesystem
      src/index.ts
      src/tools/{bash,read-file,write-file,append-file,save-memory}.ts
    web/                          # @micro-x-ai/mcp-web
    linkedin/                     # @micro-x-ai/mcp-linkedin
    github/                       # @micro-x-ai/mcp-github
    google/                       # @micro-x-ai/mcp-google
    anthropic-admin/              # @micro-x-ai/mcp-anthropic-admin
    interview-assist/             # @micro-x-ai/mcp-interview-assist
```

### Best Practices

Each server follows the standards defined in [MCP Server Best Practices](../best-practice/mcp-servers.md):

- **Tight schemas** — `additionalProperties: false` on `inputSchema`
- **outputSchema** — declared per-tool for structured validation
- **structuredContent** — machine-parseable JSON alongside TextContent
- **Structured logging** — JSON lines to stderr (never stdout)
- **MCP annotations** — `readOnlyHint` / `destructiveHint` for mutation tracking

## Tool Result Formatting

`ToolResultFormatter` converts `ToolResult.structured` into LLM-friendly text before it enters the context window. Format rules are configured per-tool in the `ToolFormatting` config section.

### Strategies

| Strategy | Config | Behaviour |
|----------|--------|-----------|
| `json` | `{"format": "json"}` | Pretty-printed JSON (default) |
| `text` | `{"format": "text", "field": "content"}` | Extract a single string field |
| `table` | `{"format": "table", "max_rows": 20}` | Markdown table from an array of objects |
| `key_value` | `{"format": "key_value"}` | `key: value` lines |

When no `structuredContent` is present, the formatter falls back to `ToolResult.text`.

### Configuration

```json
{
  "ToolFormatting": {
    "filesystem__bash": { "format": "text", "field": "stdout" },
    "filesystem__read_file": { "format": "text", "field": "content" },
    "filesystem__write_file": { "format": "key_value" },
    "web__web_search": { "format": "table", "max_rows": 20 },
    "google__gmail_search": { "format": "table", "max_rows": 15 }
  },
  "DefaultFormat": { "format": "json" }
}
```

See the config files (`config-standard.json`, etc.) for the complete mapping of all 44 tools.

## MCP Tool Adapter (McpToolProxy)

`McpToolProxy` wraps an MCP tool definition and session into a `Tool` Protocol object. All tools in the system are `McpToolProxy` instances.

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

    @property
    def output_schema(self) -> dict[str, Any] | None:
        return self._output_schema

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        result = await self._session.call_tool(self._tool_name, arguments=tool_input)
        text_parts = [block.text for block in result.content if isinstance(block, TextContent)]
        output = "\n".join(text_parts) if text_parts else "(no output)"

        # Extract structuredContent if present
        structured: dict[str, Any] | None = None
        if hasattr(result, "structuredContent") and result.structuredContent is not None:
            structured = dict(result.structuredContent)

        if result.isError:
            return ToolResult(text=output, structured=structured, is_error=True)
        return ToolResult(text=output, structured=structured)
```

| Member | Behavior |
|--------|----------|
| `name` | `{server_name}__{tool_name}` — prefixed to avoid collisions across servers |
| `description` | From the MCP tool's metadata |
| `input_schema` | From the MCP tool's `inputSchema` |
| `is_mutating` | Derived from MCP `destructiveHint` annotation |
| `output_schema` | From the MCP tool's `outputSchema` (captured at discovery time) |
| `execute()` | Calls `session.call_tool(name, arguments)`, extracts `TextContent` and `structuredContent`, returns `ToolResult` |

## McpManager

`McpManager` in `mcp/mcp_manager.py` manages the lifecycle of all MCP server connections. Each server runs in its own `asyncio.Task` with proper `async with` nesting.

- All servers start **concurrently** — processes launch in parallel, then readiness is awaited
- `connect_all()` discovers tools from each server and wraps them as `McpToolProxy` instances
- `close()` shuts down each server individually with per-server logging and a 5-second timeout
- `outputSchema` is captured from MCP tool definitions at discovery time

Connection failures for individual servers are logged but do not prevent the agent from starting. Other servers continue to work normally.

### Supported Transports

| Transport | Config | Use Case |
|-----------|--------|----------|
| `stdio` | `command`, `args`, `env` | Local MCP servers spawned as child processes |
| `http` | `url` | Remote MCP servers via StreamableHTTP |

### Third-Party MCP Servers

In addition to the 8 first-party servers (7 TypeScript + 1 Python), the agent connects to external MCP servers:

**system-info** — shared .NET MCP server from [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers):

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `system_info` | `system-info__system_info` | OS, CPU, memory, uptime, .NET runtime |
| `disk_info` | `system-info__disk_info` | Per-drive disk usage (fixed drives) |
| `network_info` | `system-info__network_info` | Network interfaces with IP addresses |

**WhatsApp** — external [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp):

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `search_contacts` | `whatsapp__search_contacts` | Search contacts by name or phone |
| `list_messages` | `whatsapp__list_messages` | Search/filter messages with pagination and context |
| `list_chats` | `whatsapp__list_chats` | List chats with search and sorting |
| `get_chat` | `whatsapp__get_chat` | Chat metadata by JID |
| `get_direct_chat_by_contact` | `whatsapp__get_direct_chat_by_contact` | Find direct chat by phone number |
| `get_contact_chats` | `whatsapp__get_contact_chats` | All chats involving a contact |
| `get_last_interaction` | `whatsapp__get_last_interaction` | Most recent message with a contact |
| `get_message_context` | `whatsapp__get_message_context` | Messages surrounding a specific message |
| `send_message` | `whatsapp__send_message` | Send text to a phone number or group JID |
| `send_file` | `whatsapp__send_file` | Send a file (image, video, document) |
| `send_audio_message` | `whatsapp__send_audio_message` | Send audio as a voice message (requires ffmpeg) |
| `download_media` | `whatsapp__download_media` | Download media from a message |

See [WhatsApp MCP](tools/whatsapp-mcp/README.md) for the full setup guide.

### Configuration

See [Configuration Reference](../operations/config.md#mcpservers) for the full config format.

## Pseudo-Tools

Pseudo-tools are tool schemas sent to the LLM that are **not** backed by MCP servers. They are handled inline in `turn_engine.py` — no MCP execution, no spinner, no checkpoint, no event callbacks. Results are returned directly as `tool_result` messages.

| Pseudo-Tool | Module | Purpose | Activation |
|-------------|--------|---------|------------|
| `tool_search` | `tool_search.py` | On-demand tool discovery — LLM searches for tools by keyword, matching schemas are loaded for the current turn | Opt-in via `ToolSearchEnabled` config |
| `ask_user` | `ask_user.py` | Human-in-the-loop questioning — LLM pauses to ask the user a clarifying question with optional structured choices | Always-on |

Both pseudo-tools follow the same pattern in `turn_engine.py`: blocks are classified in a three-way split (search / ask_user / regular), pseudo-tool results are collected into `inline_results`, and if no regular tools are present, the loop continues immediately without creating a checkpoint.

When pseudo-tools and regular tools appear in the same LLM response, pseudo-tool results are handled first, then regular tools execute in parallel, and all results are merged in the original block order before being appended to the conversation.

See [Ask User Plan](../planning/PLAN-ask-user.md) and [Tool Search Plan](../planning/PLAN-tool-search.md) for implementation details.

## Adding a New Tool

New tools are added as TypeScript MCP servers — no Python code changes are needed.

### Option A: Add a tool to an existing server

1. Create a new tool file in the relevant server's `src/tools/` directory
2. Define `inputSchema` with `additionalProperties: false` and an `outputSchema`
3. Implement the tool handler, returning both `TextContent` and `structuredContent`
4. Register the tool in the server's `src/index.ts`
5. Add a `ToolFormatting` entry in the config files for the new tool
6. Rebuild the server (`npm run build` in the server package)

### Option B: Create a new MCP server

1. Create a new package under `mcp_servers/ts/packages/`
2. Use `@micro-x-ai/mcp-shared` for validation, logging, and server factory
3. Register tools with tight schemas, `outputSchema`, and `structuredContent`
4. Add the server to `config.json` under `McpServers` with the appropriate `command`, `args`, and `env`
5. Add `ToolFormatting` entries for all tools in the new server
6. The agent will discover and expose the tools at next startup — no Python code changes needed
