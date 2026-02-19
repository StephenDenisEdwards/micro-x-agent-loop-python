# Configuration Reference

Configuration is split into two files:

- **`.env`** — secrets (API keys), loaded by python-dotenv
- **`config.json`** — application settings, loaded as JSON with `dict.get()` defaults

## Secrets (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID for Gmail and Calendar tools |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret for Gmail and Calendar tools |
| `ANTHROPIC_ADMIN_API_KEY` | No | Anthropic Admin API key (`sk-ant-admin...`) for usage/cost reporting |

If `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` is missing, Gmail and Calendar tools are not registered. If `ANTHROPIC_ADMIN_API_KEY` is missing, the `anthropic_usage` tool is not registered. All other tools work normally.

## App Settings (`config.json`)

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `Model` | string | `"claude-sonnet-4-5-20250929"` | Claude model ID to use |
| `MaxTokens` | int | `8192` | Maximum tokens per API response |
| `Temperature` | float | `1.0` | Sampling temperature (0.0 = deterministic, 1.0 = creative) |
| `MaxToolResultChars` | int | `40000` | Maximum characters per tool result before truncation |
| `MaxConversationMessages` | int | `50` | Maximum messages in conversation history before trimming |
| `CompactionStrategy` | string | `"none"` | Compaction strategy: `"none"` or `"summarize"` |
| `CompactionThresholdTokens` | int | `80000` | Estimated token count that triggers compaction |
| `ProtectedTailMessages` | int | `6` | Recent messages protected from compaction |
| `WorkingDirectory` | string | _(none)_ | Default directory for file tools and shell commands |
| `MemoryEnabled` | bool | `false` | Enables persistent session/message/tool memory in SQLite |
| `MemoryDbPath` | string | `".micro_x/memory.db"` | SQLite path for memory persistence |
| `SessionId` | string | _(none)_ | Optional logical session ID to continue (with `ContinueConversation=true`) |
| `ContinueConversation` | bool | `false` | Continue or create the configured `SessionId` |
| `ResumeSessionId` | string | _(none)_ | Resume an existing session ID; exits if missing |
| `ForkSession` | bool | `false` | Fork the resolved startup session into a new session |
| `EnableFileCheckpointing` | bool | `false` | Enable checkpoint capture for tracked mutating tools |
| `CheckpointWriteToolsOnly` | bool | `true` | Track only `write_file`/`append_file` mutations for checkpointing |
| `MemoryMaxSessions` | int | `200` | Maximum persisted sessions retained after pruning |
| `MemoryMaxMessagesPerSession` | int | `5000` | Maximum persisted messages retained per session |
| `MemoryRetentionDays` | int | `30` | Time-based retention window for persisted memory |
| `McpServers` | object | _(none)_ | MCP server configurations for external tools (see [below](#mcpservers)) |

### Example

```json
{
  "Model": "claude-sonnet-4-5-20250929",
  "MaxTokens": 8192,
  "Temperature": 1.0,
  "MaxToolResultChars": 40000,
  "MaxConversationMessages": 50,
  "CompactionStrategy": "summarize",
  "CompactionThresholdTokens": 80000,
  "ProtectedTailMessages": 6,
  "WorkingDirectory": "C:\\Users\\you\\documents",
  "MemoryEnabled": true,
  "MemoryDbPath": ".micro_x/memory.db",
  "ContinueConversation": true,
  "SessionId": "local-main",
  "EnableFileCheckpointing": true,
  "CheckpointWriteToolsOnly": true,
  "MemoryMaxSessions": 200,
  "MemoryMaxMessagesPerSession": 5000,
  "MemoryRetentionDays": 30,
  "McpServers": {
    "system-info": {
      "transport": "stdio",
      "command": "dotnet",
      "args": ["run", "--no-build", "--project", "C:\\path\\to\\mcp-servers\\system-info\\src"]
    }
  }
}
```

All settings are optional — sensible defaults are used when a setting is missing.

## Setting Details

### Model

The Anthropic model ID. Common values:

| Model | Description |
|-------|-------------|
| `claude-sonnet-4-5-20250929` | Good balance of capability and cost |
| `claude-opus-4-6` | Most capable, higher cost |
| `claude-haiku-4-5-20251001` | Fastest, lowest cost |

### MaxTokens

Controls the maximum length of Claude's response. Higher values allow longer responses but use more of your rate limit budget.

### Temperature

Controls randomness in Claude's responses:
- `0.0` — most deterministic, best for factual/precise tasks
- `1.0` — default, good general-purpose balance
- Values above 1.0 increase randomness

### MaxToolResultChars

When a tool returns more than this many characters, the output is truncated and a message is appended:

```
[OUTPUT TRUNCATED: Showing 40,000 of 85,000 characters from read_file]
```

A warning is also printed to stderr. Set to `0` to disable truncation.

### MaxConversationMessages

When the conversation history exceeds this count, the oldest messages are removed. A note is printed to stderr:

```
Note: Conversation history trimmed — removed 2 oldest message(s) to stay within the 50 message limit
```

This acts as a hard backstop after compaction. Set to `0` to disable trimming.

### CompactionStrategy

Controls how the agent manages growing conversation context:

| Value | Behavior |
|-------|----------|
| `"none"` | No compaction — only message-count trimming applies (backward-compatible default) |
| `"summarize"` | When estimated tokens exceed `CompactionThresholdTokens`, the middle of the conversation is summarized by Claude and replaced with a concise narrative |

With `"summarize"`, the first user message and the most recent `ProtectedTailMessages` messages are always preserved. Tool-use/tool-result pairs are never split at the compaction boundary. If the summarization API call fails, the agent falls back to message-count trimming.

See [Compaction Design](../design/DESIGN-compaction.md) for the full algorithm.

### CompactionThresholdTokens

The estimated token count that triggers compaction. Tokens are estimated using a chars/4 heuristic across all message content blocks. Only relevant when `CompactionStrategy` is `"summarize"`.

The default of 80,000 leaves room within Claude's 200K context window for the system prompt, tool definitions, the response, and a comfortable margin.

### ProtectedTailMessages

The number of most recent messages that are never compacted. These represent the active working context. Only relevant when `CompactionStrategy` is `"summarize"`.

The default of 6 protects approximately 3 exchange pairs (user + assistant).

### WorkingDirectory

Sets the default directory used by file and shell tools:

- **`read_file`** and **`write_file`** — relative paths are resolved against this directory
- **`bash`** — commands execute with this as the current working directory

Use an absolute path for reliability. When not set, tools use the directory where `run.bat`/`run.sh` was executed.

### MemoryEnabled, MemoryDbPath, Session Controls

When `MemoryEnabled=true`, the agent persists sessions, messages, tool calls, checkpoints, and events in SQLite.

Startup session resolution:

1. If `ResumeSessionId` is set, that session must already exist.
2. Else if `ContinueConversation=true` and `SessionId` is set, the session is loaded or created.
3. Else a new session is created.
4. If `ForkSession=true`, the resolved session is forked into a new active session.

Runtime commands when memory is enabled:

- `/session`
- `/session list [limit]`
- `/session resume <id>`
- `/session fork`
- `/rewind <checkpoint_id>`

### Checkpointing

When `EnableFileCheckpointing=true`, the agent snapshots tracked files before mutating tools execute and can restore them with `/rewind`.

- Current strict tracking target: `write_file`, `append_file`
- `CheckpointWriteToolsOnly=true` keeps tracking limited to those tools

Checkpoint rewind is best effort and reports per-file outcomes (`restored`, `removed`, `skipped`, `failed`).

### Memory Retention

Pruning runs at startup when memory is enabled:

- Time-based retention via `MemoryRetentionDays`
- Session cap via `MemoryMaxSessions`
- Per-session message cap via `MemoryMaxMessagesPerSession`

### McpServers

Configures external tool servers using the **Model Context Protocol (MCP)**. Each key is a server name, and the value is a transport configuration object. MCP tools are discovered at startup and merged with built-in tools.

Two transports are supported:

**stdio** — spawns a local process:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `transport` | string | No | `"stdio"` (default if omitted) |
| `command` | string | Yes | Executable to run |
| `args` | string[] | No | Command-line arguments |
| `env` | object | No | Environment variables for the process |

**http** — connects to a remote StreamableHTTP endpoint:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `transport` | string | Yes | Must be `"http"` |
| `url` | string | Yes | StreamableHTTP endpoint URL |

Example — the system-info server (from the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo):

```json
{
  "McpServers": {
    "system-info": {
      "transport": "stdio",
      "command": "dotnet",
      "args": ["run", "--no-build", "--project", "C:\\path\\to\\mcp-servers\\system-info\\src"]
    }
  }
}
```

> **Note:** For stdio servers that have a build step (like .NET or TypeScript projects), use `--no-build` (or equivalent) to prevent build output from being written to stdout, which would corrupt the JSONRPC transport. Build the server separately before starting the agent (e.g., `dotnet build path/to/mcp-servers/system-info/src`).

Example — the external WhatsApp MCP server (see [WhatsApp MCP docs](../design/tools/whatsapp-mcp/README.md)):

```json
{
  "McpServers": {
    "whatsapp": {
      "transport": "stdio",
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\whatsapp-mcp\\whatsapp-mcp-server", "run", "main.py"]
    }
  }
}
```

> **Note:** The WhatsApp MCP server requires a separate Go bridge process to be running. The bridge connects to WhatsApp Web and must be started manually before the agent. See [WhatsApp MCP](../design/tools/whatsapp-mcp/README.md) for the full setup guide.

Example with both transports:

```json
{
  "McpServers": {
    "system-info": {
      "transport": "stdio",
      "command": "dotnet",
      "args": ["run", "--no-build", "--project", "C:\\path\\to\\mcp-servers\\system-info\\src"]
    },
    "whatsapp": {
      "transport": "stdio",
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\whatsapp-mcp\\whatsapp-mcp-server", "run", "main.py"]
    },
    "remote-tools": {
      "transport": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

MCP tool names appear prefixed as `{server_name}__{tool_name}` in the Tools list at startup. If a server fails to connect, a warning is logged but the agent starts normally with the remaining tools.

See [ADR-005](../architecture/decisions/ADR-005-mcp-for-external-tools.md) for the architectural decision and [Tool System Design](../design/DESIGN-tool-system.md#mcp-tools-dynamic) for implementation details.
