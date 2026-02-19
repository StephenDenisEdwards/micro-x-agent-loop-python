# Design: Tool System

## Overview

The tool system provides Claude with the ability to interact with the outside world. Each tool is a self-contained unit that accepts a dict input, performs an action, and returns a string result.

## Tool Protocol

```python
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
```

| Member | Purpose |
|--------|---------|
| `name` | Unique identifier sent to Claude (e.g., `"read_file"`) |
| `description` | Natural-language description Claude uses to decide when to call the tool |
| `input_schema` | JSON Schema dict defining the expected input parameters |
| `execute` | Executes the tool and returns a string result |

Using `typing.Protocol` provides structural typing — any class with matching properties and methods satisfies the interface without explicit inheritance.

## Tool Registry

`tool_registry.get_all()` assembles the tool list with their dependencies:

```python
def get_all(
    working_directory: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
    anthropic_admin_api_key: str | None = None,
) -> list[Tool]:
```

Gmail/Calendar tools are **conditionally registered** when both Google credentials are present. The Anthropic usage tool is conditionally registered when the admin API key is present. This prevents runtime errors when optional credentials are not configured.

## Built-in Tools

Each tool has its own detailed documentation in the [tools/](tools/) directory.

### File System

| Tool | Description | Docs |
|------|-------------|------|
| `read_file` | Read text files and `.docx` documents | [read-file](tools/read-file/README.md) |
| `write_file` | Write content to a file, creating directories as needed | [write-file](tools/write-file/README.md) |

### Shell

| Tool | Description | Docs |
|------|-------------|------|
| `bash` | Execute a shell command (cmd.exe on Windows, bash on Unix) | [bash](tools/bash/README.md) |

### LinkedIn

| Tool | Description | Docs |
|------|-------------|------|
| `linkedin_jobs` | Search LinkedIn job postings with filters | [linkedin-jobs](tools/linkedin-jobs/README.md) |
| `linkedin_job_detail` | Fetch full job description from a LinkedIn URL | [linkedin-job-detail](tools/linkedin-job-detail/README.md) |

### Gmail (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `gmail_search` | Search Gmail using Gmail search syntax | [gmail-search](tools/gmail-search/README.md) |
| `gmail_read` | Read full email content by message ID | [gmail-read](tools/gmail-read/README.md) |
| `gmail_send` | Send a plain-text email | [gmail-send](tools/gmail-send/README.md) |

Gmail tools require OAuth2 authentication. On first use, a browser window opens for Google sign-in. Tokens are cached in `.gmail-tokens/`. See [ADR-004](../architecture/decisions/ADR-004-raw-html-for-gmail.md) for the decision to pass raw HTML to the LLM.

### Google Calendar (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `calendar_list_events` | List events by date range or search query | [calendar-list-events](tools/calendar-list-events/README.md) |
| `calendar_create_event` | Create events with title, time, attendees | [calendar-create-event](tools/calendar-create-event/README.md) |
| `calendar_get_event` | Get full event details by ID | [calendar-get-event](tools/calendar-get-event/README.md) |

Calendar tools use the same Google OAuth2 credentials as Gmail but with a separate token cache (`.calendar-tokens/`) and the `https://www.googleapis.com/auth/calendar` scope.

### Anthropic Admin (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `anthropic_usage` | Query usage, cost, and Claude Code productivity reports | [anthropic-usage](tools/anthropic-usage/README.md) |

Requires an Anthropic Admin API key (`sk-ant-admin...`), separate from the inference key. See [DESIGN-account-management-apis](DESIGN-account-management-apis.md) for full API surface details.

## MCP Tools (dynamic)

The agent supports dynamically discovering tools from external **MCP (Model Context Protocol)** servers. MCP tools are configured in `config.json` under `McpServers` — no code changes are needed to add new tool servers.

See [ADR-005](../architecture/decisions/ADR-005-mcp-for-external-tools.md) for the architectural decision.

### How It Works

1. At startup, `McpManager` reads the `McpServers` config and connects to each server
2. For each server, it calls `list_tools()` to discover available tools
3. Each discovered tool is wrapped in `McpToolProxy`, which adapts it to the `Tool` Protocol
4. MCP tools are merged with built-in tools and passed to the agent

The agent dispatches MCP tools identically to built-in tools — no special handling is needed.

### McpToolProxy

`McpToolProxy` is an adapter class in `mcp/mcp_tool_proxy.py` that wraps an MCP tool definition and session into a `Tool` Protocol object:

| Member | Behavior |
|--------|----------|
| `name` | `{server_name}__{tool_name}` — prefixed to avoid collisions with built-in tools |
| `description` | From the MCP tool's metadata |
| `input_schema` | From the MCP tool's `inputSchema` |
| `execute()` | Calls `session.call_tool(name, arguments)`, extracts text from result content blocks |

### McpManager

`McpManager` in `mcp/mcp_manager.py` manages the lifecycle of all MCP server connections. Each server runs in its own `asyncio.Task` with proper `async with` nesting (avoiding `AsyncExitStack`, which conflicts with anyio's cancel scopes used internally by `stdio_client`).

- `connect_all()` — starts each server in a background task, waits for it to be ready, returns discovered tools
- `close()` — shuts down each server individually with per-server logging and a 5-second timeout

Shutdown signals both the internal shutdown event and task cancellation together, ensuring both anyio and asyncio cleanup paths are triggered. On Windows, a `sys.unraisablehook` in `__main__.py` suppresses harmless "unclosed transport" noise from asyncio's proactor pipe cleanup.

Connection failures for individual servers are logged but do not prevent the agent from starting. Other servers and built-in tools continue to work normally.

### Supported Transports

| Transport | Config | Use Case |
|-----------|--------|----------|
| `stdio` | `command`, `args`, `env` | Local MCP servers spawned as child processes |
| `http` | `url` | Remote MCP servers via StreamableHTTP |

### Shared MCP Server: system-info

The system-info MCP server lives in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repository (used by both the Python and .NET agents). It demonstrates the stdio transport pattern and exposes three tools:

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `system_info` | `system-info__system_info` | OS, CPU, memory, uptime, .NET runtime |
| `disk_info` | `system-info__disk_info` | Per-drive disk usage (fixed drives) |
| `network_info` | `system-info__network_info` | Network interfaces with IP addresses |

Built with the [ModelContextProtocol](https://www.nuget.org/packages/ModelContextProtocol) NuGet package and `Microsoft.Extensions.Hosting`. Uses `Host.CreateEmptyApplicationBuilder(settings: null)` to avoid default logging to stdout (which would corrupt the stdio transport).

The server must be built before starting the agent (`dotnet build path/to/mcp-servers/system-info/src`). The config uses `--no-build` to skip the build step at runtime, and an absolute path to the server project.

### External MCP Server: WhatsApp

The agent can also connect to the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) external MCP server for WhatsApp messaging. Unlike system-info, this server lives outside this repository and has a two-component architecture:

| Component | Role |
|-----------|------|
| Go bridge (`whatsapp-bridge/`) | Connects to WhatsApp Web via whatsmeow, stores messages in SQLite, exposes HTTP API on port 8080 |
| Python MCP server (`whatsapp-mcp-server/`) | FastMCP server that queries SQLite for messages and calls the bridge API for sending. Runs via `uv` as a stdio MCP server. |

The Go bridge must be running before the agent starts. The Python MCP server is spawned by McpManager as a child process.

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
| `send_message` | `whatsapp__send_message` | Send text to phone number or group JID |
| `send_file` | `whatsapp__send_file` | Send file (image, video, document) |
| `send_audio_message` | `whatsapp__send_audio_message` | Send audio as voice message (requires ffmpeg) |
| `download_media` | `whatsapp__download_media` | Download media from a message |

See [WhatsApp MCP](tools/whatsapp-mcp/README.md) for the full setup guide, prerequisites (Go, GCC, uv), Windows CGO pain points, and known limitations.

### External MCP Server: Interview Assist

The agent can also connect to the local Interview Assist MCP wrapper for session analysis/evaluation and speech-to-text workflows.

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `ia_healthcheck` | `interview-assist__ia_healthcheck` | Validate Interview Assist repo/project setup |
| `ia_evaluate_session` | `interview-assist__ia_evaluate_session` | Evaluate transcript/session detection metrics |
| `ia_transcribe_once` | `interview-assist__ia_transcribe_once` | One-shot microphone/loopback transcription |
| `stt_list_devices` | `interview-assist__stt_list_devices` | List available STT sources |
| `stt_start_session` | `interview-assist__stt_start_session` | Start continuous STT polling session |
| `stt_get_updates` | `interview-assist__stt_get_updates` | Retrieve incremental STT events |
| `stt_get_session` | `interview-assist__stt_get_session` | Read STT session status/counters |
| `stt_stop_session` | `interview-assist__stt_stop_session` | Stop STT session |

See [Interview Assist MCP](tools/interview-assist-mcp/README.md) for setup and tool details.

### Configuration

See [Configuration Reference](../operations/config.md#mcpservers) for the full config format.

## Shared Utilities

### HtmlUtilities

`html_utilities.html_to_text(html)` converts HTML to readable plain text. Used by LinkedIn tools for job description extraction.

Handles:
- Block elements (p, div, h1-h6, blockquote, tr) with newlines
- Link URL preservation (`<a href="url">text</a>` becomes `text (url)`)
- List items with bullet markers
- Table cells with tab separation
- Script/style removal
- HTML entity decoding
- Whitespace normalization

### GmailParser

- `decode_body` — base64url decoding for Gmail message bodies
- `extract_text` — recursive MIME parsing, prefers HTML over plain text for multipart/alternative
- `get_header` — case-insensitive header lookup

## Adding a New Tool

1. Create a class in the `tools/` directory with matching `Tool` Protocol members
2. Define `name`, `description`, and `input_schema` properties
3. Implement `async execute()` with error handling (return error strings, don't raise)
4. Register it in `tool_registry.get_all()`

Example skeleton:

```python
from typing import Any


class MyTool:
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",
                    "description": "A required parameter",
                }
            },
            "required": ["param"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        param = tool_input["param"]
        try:
            # Do work
            return "Result"
        except Exception as ex:
            return f"Error: {ex}"
```
