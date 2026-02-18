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
  "WorkingDirectory": "C:\\Users\\you\\documents"
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
