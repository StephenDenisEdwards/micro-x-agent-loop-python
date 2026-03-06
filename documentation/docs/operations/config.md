# Configuration Reference

Configuration is split into two files:

- **`.env`** — secrets (API keys), loaded by python-dotenv
- **`config.json`** — application settings, loaded as JSON with `dict.get()` defaults

## Config File Indirection

`config.json` can act as a thin pointer to the actual settings file using the `ConfigFile` field. This lets you maintain multiple config variants and switch between them by changing a single line.

**Resolution order:**

1. `--config <path>` CLI argument (highest priority)
2. `ConfigFile` field in `./config.json`
3. `./config.json` itself (backward compatible — if no `ConfigFile` field, settings are read directly)

### Pointer mode

```json
{
  "ConfigFile": "config-standard.json"
}
```

The agent loads all settings from `config-standard.json` in the current directory. Switch profiles by changing the `ConfigFile` value:

- `config-standard.json` — all cost reduction features enabled (including tool result summarization — see [warning](#toolresultsummarizationenabled-toolresultsummarizationmodel-toolresultsummarizationthreshold))
- `config-standard-no-summarization.json` — recommended for general use; all cost savings except tool result summarization
- `config-baseline.json` — all cost reduction features disabled (useful for A/B cost comparison)

### CLI override

```bash
python -m micro_x_agent_loop --config config-baseline.json
```

This ignores `config.json` entirely and loads settings from the specified file. The path is resolved relative to the current working directory.

### Backward compatible

If `config.json` contains settings directly (no `ConfigFile` field), it works exactly as before — no migration needed.

### Startup message

The agent prints which config file is active at startup:

```
Config: config-standard.json
```

## Secrets (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | When `Provider` = `anthropic` | Anthropic API key for Claude |
| `OPENAI_API_KEY` | When `Provider` = `openai` | OpenAI API key for GPT models |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID for Gmail and Calendar tools |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret for Gmail and Calendar tools |
| `ANTHROPIC_ADMIN_API_KEY` | No | Anthropic Admin API key (`sk-ant-admin...`) for usage/cost reporting |

The required API key depends on the configured `Provider`. Service-specific credentials (Google, Brave, GitHub, Anthropic Admin) are passed to MCP servers via `env` blocks in `McpServers` config — they no longer need to be in `.env`.

## App Settings (`config.json`)

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `ConfigFile` | string | _(none)_ | Path to the actual config file (see [Config File Indirection](#config-file-indirection)) |
| `Provider` | string | `"anthropic"` | LLM provider: `"anthropic"` or `"openai"` |
| `Model` | string | `"claude-sonnet-4-5-20250929"` | Model ID to use (provider-specific) |
| `MaxTokens` | int | `8192` | Maximum tokens per API response |
| `Temperature` | float | `0.7` | Sampling temperature — tuned for agentic tool-use reliability (see [Temperature](#temperature)) |
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
| `ResumeSessionId` | string | _(none)_ | Resume an existing session ID or exact session name; exits if missing/ambiguous |
| `ForkSession` | bool | `false` | Fork the resolved startup session into a new session |
| `EnableFileCheckpointing` | bool | `false` | Enable checkpoint capture for tracked mutating tools |
| `CheckpointWriteToolsOnly` | bool | `true` | Track only `write_file`/`append_file` mutations for checkpointing |
| `MemoryMaxSessions` | int | `200` | Maximum persisted sessions retained after pruning |
| `MemoryMaxMessagesPerSession` | int | `5000` | Maximum persisted messages retained per session |
| `MemoryRetentionDays` | int | `30` | Time-based retention window for persisted memory |
| `MetricsEnabled` | bool | `true` | Enables structured cost metrics collection and emission |
| `PromptCachingEnabled` | bool | `true` | Enables Anthropic prompt caching for system prompt and tool schemas |
| `CompactionModel` | string | `""` | Model for compaction summarization; empty = use main `Model` |
| `ToolResultSummarizationEnabled` | bool | `false` | Summarize large tool results before feeding back to the main model |
| `ToolResultSummarizationModel` | string | `""` | Model for tool result summarization; empty = use main `Model` |
| `ToolResultSummarizationThreshold` | int | `4000` | Minimum tool result chars before summarization is attempted |
| `SmartCompactionTriggerEnabled` | bool | `true` | Use actual API token counts instead of estimates for compaction trigger |
| `ConciseOutputEnabled` | bool | `false` | Adds a system prompt directive to minimize output token spend |
| `ToolFormatting` | object | `{}` | Per-tool format rules for structured result formatting (see [Tool System Design](../design/DESIGN-tool-system.md#tool-result-formatting)) |
| `DefaultFormat` | object | `{"format": "json"}` | Default format when no per-tool rule matches |
| `LogLevel` | string | `"INFO"` | Minimum log level for console and file consumers |
| `LogConsumers` | array | console + file | Log sink configuration (see [below](#logconsumers)) |
| `UserMemoryEnabled` | bool | `false` | Enables persistent user memory (MEMORY.md files) |
| `UserMemoryDir` | string | _(none)_ | Directory for user memory files (requires `UserMemoryEnabled=true`) |
| `McpServers` | object | _(none)_ | MCP server configurations (see [below](#mcpservers)) |

### Example

```json
{
  "Provider": "anthropic",
  "Model": "claude-sonnet-4-5-20250929",
  "MaxTokens": 8192,
  "Temperature": 0.7,
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
  "MetricsEnabled": true,
  "PromptCachingEnabled": true,
  "CompactionModel": "",
  "ToolResultSummarizationEnabled": false,
  "ToolResultSummarizationModel": "claude-haiku-4-5-20251001",
  "ToolResultSummarizationThreshold": 4000,
  "SmartCompactionTriggerEnabled": true,
  "ConciseOutputEnabled": false,
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

### Provider

Selects the LLM backend. The agent routes the API key and message format automatically.

| Value | API Key Variable | Description |
|-------|-----------------|-------------|
| `"anthropic"` | `ANTHROPIC_API_KEY` | Anthropic Claude models (default) |
| `"openai"` | `OPENAI_API_KEY` | OpenAI GPT models |

The internal message format remains Anthropic-style regardless of provider. The OpenAI provider translates at the API boundary. See [ADR-010](../architecture/decisions/ADR-010-multi-provider-llm-support.md).

### Model

The model ID to use. The value is provider-specific.

**Anthropic models:**

| Model | Description |
|-------|-------------|
| `claude-sonnet-4-5-20250929` | Good balance of capability and cost |
| `claude-opus-4-6` | Most capable, higher cost |
| `claude-haiku-4-5-20251001` | Fastest, lowest cost |

**OpenAI models:**

| Model | Description |
|-------|-------------|
| `gpt-4o` | Most capable GPT-4 variant |
| `gpt-4o-mini` | Faster, lower cost |
| `o1` | Reasoning model |
| `o3` | Latest reasoning model |

### MaxTokens

Controls the maximum length of Claude's response. Higher values allow longer responses but use more of your rate limit budget.

### Temperature

Controls randomness in the model's responses. The default is `0.7`, tuned for agentic tool-use reliability.

| Value | Behaviour |
|-------|-----------|
| `0.0` | Most deterministic — nearly identical output for the same input |
| `0.5–0.7` | Recommended for agentic/tool-heavy workloads — reduces randomness in tool calls and structured output while retaining enough variation for natural language |
| `1.0` | Provider API default — good general-purpose balance for conversational use |
| `>1.0` | Increases randomness (OpenAI supports up to 2.0; Anthropic caps at 1.0) |

**Why `0.7`?** The provider API default is `1.0`, but this is an agent loop, not a chatbot. The primary workload is tool-heavy — file operations, MCP calls, code generation — where deterministic, reliable tool calls matter more than creative variation. `0.7` retains enough variation for natural conversational responses while reducing noise in structured output. Set to `1.0` if you prefer the provider default for more conversational use cases.

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

Runtime commands (always available):

- `/cost` — session cost summary (see [MetricsEnabled](#metricsenabled))

Runtime commands when memory is enabled:

- `/session`
- `/session new [title]`
- `/session list [limit]`
- `/session name <title>`
- `/session resume <id-or-name>`
- `/session fork`
- `/rewind <checkpoint_id>`
- `/checkpoint list [limit]`
- `/checkpoint rewind <checkpoint_id>`

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

### MetricsEnabled

When `true` (the default), the agent collects structured cost metrics for every API call, tool execution, and compaction event. Metrics are accumulated in-memory and available via the `/cost` REPL command.

To persist metrics to a file, add the `"metrics"` log consumer:

```json
{
  "LogConsumers": [
    {"type": "console"},
    {"type": "file", "path": "agent.log"},
    {"type": "metrics", "path": "metrics.jsonl"}
  ]
}
```

The metrics file contains one JSON record per line. Records have a `type` field: `api_call`, `tool_execution`, `compaction`, or `session_summary`.

### LogConsumers

Controls where log output is written. Each entry in the array is a sink with a `type` field and optional parameters.

| Type | Description | Parameters |
|------|-------------|------------|
| `console` | Writes to stderr | _(none)_ |
| `file` | Structured log file | `path` (default: `agent.log`) |
| `metrics` | JSON Lines metrics | `path` (default: `metrics.jsonl`) |
| `api_payload` | Full API request/response payloads | `path` (default: `api_payloads.jsonl`) |

Default when `LogConsumers` is not specified: `[{"type": "console"}, {"type": "file"}]`.

The `api_payload` consumer captures every API request/response as a JSON line, including the resolved system prompt, full message array, tool count, response, usage, and estimated cost. Useful for debugging prompt issues, cost surprises, or unexpected LLM behaviour. The payloads are also kept in an in-memory ring buffer (last 50) accessible via `/debug show-api-payload [N]`.

Example with all consumers:

```json
{
  "LogConsumers": [
    {"type": "console"},
    {"type": "file", "path": "agent.log"},
    {"type": "metrics", "path": "metrics.jsonl"},
    {"type": "api_payload", "path": "api_payloads.jsonl"}
  ]
}
```

Runtime commands (always available, not gated by `MemoryEnabled`):

- `/cost` — prints the current session's accumulated cost summary
- `/tool` — list all loaded tools grouped by MCP server
- `/tool <name>` — show tool name, description, and mutating flag
- `/tool <name> schema` — show input (and output) JSON schema
- `/tool <name> config` — show ToolFormatting config for the tool
- `/debug show-api-payload [N]` — inspect the Nth most recent API request/response (0 = latest)
- `/prompt <filename>` — read a file and use its contents as the user message
- `/command` — list available prompt commands from `.commands/` directory
- `/command <name> [arguments]` — run a prompt command (see [Prompt Commands](#prompt-commands))

Runtime commands when `UserMemoryEnabled=true`:

- `/memory` — show contents of MEMORY.md
- `/memory list` — list all memory files
- `/memory edit` — open MEMORY.md in `$EDITOR`
- `/memory reset` — delete all memory files (requires `/memory reset confirm`)

Analysis CLI:

```bash
python -m micro_x_agent_loop.analyze_costs --file metrics.jsonl
python -m micro_x_agent_loop.analyze_costs --session <id>
python -m micro_x_agent_loop.analyze_costs --compare <session_a> <session_b>
python -m micro_x_agent_loop.analyze_costs --csv
```

See [Cost Metrics Design](../design/DESIGN-cost-metrics.md) for the full architecture.

### Cost Reduction

These settings control cost optimisation features. All are optional with sensible defaults — prompt caching and smart compaction trigger are on by default; the others are opt-in.

#### PromptCachingEnabled

Enables Anthropic's prompt caching. When `true`, the system prompt and tool schemas are tagged with `cache_control: {"type": "ephemeral"}` breakpoints, allowing subsequent turns to read from cache at 10% of the normal input token price.

- Only affects the Anthropic provider. OpenAI does automatic prefix caching — no explicit headers needed.
- Cache hits appear in `/cost` as "Cache read tokens".
- Requires a minimum prefix length of 1,024 tokens (system prompt + tool schemas typically exceed this).

#### CompactionModel

Model used for the compaction summarization call. When empty (the default), the main `Model` is used. Setting this to a cheaper model (e.g. `"claude-haiku-4-5-20251001"` at $0.25/$1.25 per MTok vs Sonnet at $3/$15) reduces compaction cost by 70-90%.

Compaction is a straightforward summarization task and does not require the full reasoning capability of the main model.

#### ToolResultSummarizationEnabled, ToolResultSummarizationModel, ToolResultSummarizationThreshold

> **Warning: not recommended for general-purpose use.** Tool result summarization is fundamentally lossy — the summarization model cannot reliably determine which parts of a tool result matter to the user's task. In practice, this causes missing data in agent output (e.g., dropped URLs from web searches, lost records from multi-item results). Mechanical truncation (head+tail) has the same problem for unstructured content. See [ADR-013](../architecture/decisions/ADR-013-tool-result-summarization-reliability.md) for the full analysis.
>
> Use `config-standard-no-summarization.json` for general assistant workloads. Only enable summarization for loss-tolerant tasks (e.g., log analysis where the gist suffices).

When enabled, tool results longer than `ToolResultSummarizationThreshold` characters are summarized by a separate LLM call before being fed back to the main model. This reduces per-turn input tokens for tool-heavy workflows (web fetches, large file reads, etc.).

- `ToolResultSummarizationModel` — model for summarization; empty = use main `Model`. Haiku is recommended.
- `ToolResultSummarizationThreshold` — minimum result size (in characters) before summarization kicks in. Default 4,000.
- The summarization prompt preserves decision-relevant data: names, numbers, IDs, paths, errors.
- If summarization fails, the original (truncated) result is used as a fallback.
- Summarized tool results are flagged as `was_summarized: true` in metrics.

#### SmartCompactionTriggerEnabled

When `true`, the compaction trigger uses actual API-reported input token counts (from `response.usage`) instead of the tiktoken character-based estimate. The tiktoken estimate can be 10-20% off (wrong encoding for Claude, doesn't count system/tool schema overhead). Actual counts lead to better-timed compaction — neither too early (wasting a summarization call) nor too late (accumulating unnecessary input cost).

Falls back to the tiktoken estimate on the first turn before any API response has been received.

#### ConciseOutputEnabled

When `true`, appends a directive to the system prompt instructing the model to minimize output tokens: use bullet points, omit filler, target 200 words per response. Output tokens are 5x more expensive than input ($15 vs $3 per MTok for Sonnet), so reducing verbosity directly cuts the most expensive token class.

Off by default because it changes response style. Enable when cost is a higher priority than conversational tone.

#### Estimated Cost Impact

All estimates assume Sonnet ($3/$15 per MTok input/output) as the main model and a typical 10-turn session with moderate tool use and one compaction event.

| Feature | Mechanism | Est. Saving per Session | Quality Tradeoff |
|---------|-----------|------------------------|------------------|
| Prompt Caching | Cache reads at 10% of input price ($0.30 vs $3.00/MTok) for system prompt + tool schemas (~5-10K tokens/turn) | ~$0.12-0.24 | None |
| Compaction Model (Haiku) | Haiku compaction at $0.03/event vs Sonnet at $0.36/event | ~$0.33 per event | Minimal — summarization is a simple task |
| Tool Result Summarization | Reduces large tool results (5-10K chars) to summaries (~500 chars); savings compound as summaries stay in conversation history | 30-60% of tool-result-driven input cost | Some detail loss — mitigated by preserving key data |
| Smart Compaction Trigger | Uses actual API token counts instead of ±10-20% tiktoken estimates | 15-30% improvement in compaction timing | None |
| Concise Output | 30-50% shorter responses at $15/MTok output price | ~$0.09-0.15 | More terse responses |

**Combined estimate:** ~40-50% reduction in total session cost (from ~$2.00-2.50 to ~$1.00-1.50 for a typical session).

Features enabled by default (prompt caching, smart trigger) are pure wins with no quality tradeoff. Opt-in features (tool summarization, concise output) trade some fidelity for cost. The cheapest single change is setting `CompactionModel` to Haiku — a ~91% reduction per compaction event with negligible quality impact.

### McpServers

Configures tool servers using the **Model Context Protocol (MCP)**. Each key is a server name, and the value is a transport configuration object. All tools in the system come from MCP servers — there are no built-in Python tools.

Two transports are supported:

**stdio** — spawns a local process:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `transport` | string | No | `"stdio"` (default if omitted) |
| `command` | string | Yes | Executable to run |
| `args` | string[] | No | Command-line arguments |
| `env` | object | No | Environment variables for the process |

`env` values override inherited process environment variables for that MCP server. Parent environment variables (including values loaded from `.env`) are still passed through unless explicitly overridden.

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

Example - Interview Assist MCP server (see [Interview Assist MCP docs](../design/tools/interview-assist-mcp/README.md)):

```json
{
  "McpServers": {
    "interview-assist": {
      "transport": "stdio",
      "command": "node",
      "args": ["C:\\path\\to\\micro-x-agent-loop-python\\mcp_servers\\ts\\packages\\interview-assist\\dist\\index.js"],
      "env": {
        "INTERVIEW_ASSIST_REPO": "C:\\path\\to\\interview-assist-2"
      }
    }
  }
}
```

Example — the codegen server (Python FastMCP, see [DESIGN-codegen-server](../design/DESIGN-codegen-server.md)):

```json
{
  "McpServers": {
    "codegen": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "uv", "--directory", "C:\\path\\to\\micro-x-agent-loop-python\\mcp_servers\\python\\codegen", "run", "main.py"],
      "env": {
        "PROJECT_ROOT": "C:\\path\\to\\micro-x-agent-loop-python",
        "WORKING_DIR": "C:\\path\\to\\resources\\documents"
      }
    }
  }
}
```

> **Note:** The codegen server makes Anthropic API calls directly, so `ANTHROPIC_API_KEY` must be set in `.env` or the process environment.

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

### Prompt Commands

Prompt commands are reusable prompt templates stored as Markdown files in a `.commands/` directory inside `WorkingDirectory`. They provide a discoverable, repeatable way to run common agent tasks.

The commands are contextual to the workspace — different working directories can have different commands.

#### Directory

```
.commands/
├── review.md
├── explain.md
└── ...
```

Each `.md` file is a command. The filename (without extension) becomes the command name.

#### File format

- **First line** — short description, shown in the `/command` listing
- **Rest of file** — the prompt sent to the agent
- **`$ARGUMENTS`** — placeholder replaced with any arguments passed after the command name

Example `.commands/explain.md`:

```
Explain how the following file or component works.
Give a concise overview of its purpose, key classes/functions, and how it fits
into the broader architecture. Keep the explanation short and practical.

File or component: $ARGUMENTS
```

#### Usage

```
you> /command
assistant> Available commands:
             explain  Explain how the following file or component works.
             review   Review the current git diff for bugs and style issues.

you> /command explain src/micro_x_agent_loop/agent.py
```

When `/command explain src/micro_x_agent_loop/agent.py` is entered, the agent loads `explain.md`, replaces `$ARGUMENTS` with `src/micro_x_agent_loop/agent.py`, and executes the resulting text as the user prompt.
