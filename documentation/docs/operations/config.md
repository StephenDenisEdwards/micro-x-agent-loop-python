# Configuration Reference

Configuration is split into two files:

- **`.env`** — secrets (API keys), loaded by python-dotenv
- **`config.json`** — application settings, loaded as JSON with `dict.get()` defaults

## Secrets (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID for Gmail tools |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret for Gmail tools |

If `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` is missing, Gmail tools are not registered. All other tools work normally.

## App Settings (`config.json`)

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `Model` | string | `"claude-sonnet-4-5-20250929"` | Claude model ID to use |
| `MaxTokens` | int | `8192` | Maximum tokens per API response |
| `Temperature` | float | `1.0` | Sampling temperature (0.0 = deterministic, 1.0 = creative) |
| `MaxToolResultChars` | int | `40000` | Maximum characters per tool result before truncation |
| `MaxConversationMessages` | int | `50` | Maximum messages in conversation history before trimming |
| `InputTokenBudget` | int | `40000` | Input token threshold that triggers old tool result compaction |
| `ToolResultRetentionChars` | int | `500` | Characters to keep from each old tool result after compaction |
| `WorkingDirectory` | string | _(none)_ | Default directory for file tools and shell commands |

### Example

```json
{
  "Model": "claude-sonnet-4-5-20250929",
  "MaxTokens": 8192,
  "Temperature": 1.0,
  "MaxToolResultChars": 40000,
  "MaxConversationMessages": 50,
  "InputTokenBudget": 40000,
  "ToolResultRetentionChars": 500,
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

This helps prevent rate limit errors from growing context. Set to `0` to disable trimming.

### InputTokenBudget

When the input token count from an API response exceeds this budget, old tool-result messages are compacted — their content is truncated to `ToolResultRetentionChars` characters with a marker appended:

```
[truncated for context management]
```

The most recent tool result is always kept in full. A note is printed to stderr when compaction occurs:

```
Note: Compacted 3 old tool result(s) — input tokens (45,231) exceeded budget (40,000)
```

Set to `0` to disable compaction entirely. This is useful for tool-heavy workflows (Gmail, LinkedIn) where stale results accumulate and push input tokens toward rate limits.

### ToolResultRetentionChars

The number of characters to retain from each old tool result when compaction is triggered. The retained prefix gives the LLM enough context to know what the tool returned, without carrying the full content.

A value of `500` typically preserves the first few lines of output — enough for headings, summaries, or the start of a document.

### WorkingDirectory

Sets the default directory used by file and shell tools:

- **`read_file`** and **`write_file`** — relative paths are resolved against this directory
- **`bash`** — commands execute with this as the current working directory

Use an absolute path for reliability. When not set, tools use the directory where `run.bat`/`run.sh` was executed.
