# Template Console App

Reusable template for building AI-adapted console apps that use MCP servers and Claude LLM. Copy this directory, edit `run_task()`, and run.

## Quick Start

```bash
# 1. Copy the template
cp -r tools/template tools/my_task

# 2. Edit run_task() in __main__.py with your orchestration logic

# 3. Run from project root
python -m tools.my_task
python -m tools.my_task --config path/to/config.json
```

## Architecture

```
tools/template/
├── __init__.py      # Empty package marker
├── __main__.py      # Entry point: config → MCP connect → discover tools → run_task()
├── mcp_client.py    # MCP stdio client: connect, list_tools, call_tool, close
├── llm.py           # LLM helper: create_message, stream_message, cost tracking
└── README.md        # This file
```

The app is **self-contained** — config loading is copied into `__main__.py`, not imported from `src/`. Copied tools work without depending on the main agent package.

## MCP Tool Calling

### Calling a tool

```python
result = await clients["google"].call_tool("gmail_search", {
    "query": "from:alerts@example.com newer_than:1d",
    "maxResults": 10,
})
```

### structuredContent handling

MCP tools return `structuredContent` (a JSON dict) when available. The client handles this automatically:

```python
# result is already a dict — use it directly
emails = result["emails"]       # Access fields directly
count = result["totalCount"]    # No json.loads() needed

# If structuredContent is not available, result is a plain string
```

**Important:** Never `json.loads()` on the result. The client returns structuredContent (dict) directly, or falls back to concatenated text (string).

### Discovering available tools

```python
tools = await client.list_tools()  # [(name, description), ...]
for name, desc in tools:
    print(f"  {name}: {desc}")
```

## LLM Calling

### Non-streaming (batch processing)

```python
from .llm import create_message, estimate_cost

text, usage = await create_message(
    model="claude-haiku-4-5-20251001",
    max_tokens=4096,
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": "Summarize this data: ..."}],
)
print(text)
print(f"Cost: ${estimate_cost(usage):.4f}")
```

### Streaming (interactive output)

```python
from .llm import stream_message, estimate_cost

text, usage = await stream_message(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8192,
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": "Write a report about..."}],
)
# Text prints to stdout in real-time during streaming.
# 'text' contains the complete response after streaming finishes.
print(f"\nCost: ${estimate_cost(usage):.4f}")
```

### Accumulating cost across multiple calls

```python
from .llm import Usage, estimate_cost

total = Usage()
for item in work_items:
    text, usage = await create_message(...)
    total = total + usage
print(f"Total cost: ${estimate_cost(total):.4f}")
```

### Model selection

| Model | ID | Best for | Input $/M | Output $/M |
|-------|-----|----------|-----------|------------|
| Haiku | `claude-haiku-4-5-20251001` | Scoring, classification, simple generation | $0.80 | $4.00 |
| Sonnet | `claude-sonnet-4-5-20250929` | General tasks, report writing | $3.00 | $15.00 |
| Opus | `claude-opus-4-6` | Complex reasoning, code generation | $15.00 | $75.00 |

Use `config.get("Model")` to read the model from config, or hardcode for cost control.

## Config

The app reads the same config files as the main agent:

1. `--config path/to/file.json` (CLI flag) — loads directly
2. `ConfigFile` field in `./config.json` — follows indirection
3. `./config.json` — direct use

### Key config fields

| Field | Type | Description |
|-------|------|-------------|
| `Model` | string | Default model ID |
| `MaxTokens` | int | Default max response tokens |
| `Temperature` | float | Sampling temperature (0.0–1.0) |
| `McpServers` | dict | MCP server configurations (see below) |
| `PromptCachingEnabled` | bool | Whether to use prompt caching |

### MCP server config format

```json
{
  "McpServers": {
    "server-name": {
      "transport": "stdio",
      "command": "node",
      "args": ["path/to/server.js"],
      "env": { "EXTRA_VAR": "value" }
    }
  }
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (for LLM) | Anthropic API key |
| `GITHUB_TOKEN` | For github MCP | GitHub personal access token |
| `GOOGLE_CLIENT_ID` | For google MCP | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | For google MCP | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | For google MCP | Google OAuth refresh token |

These are typically set in a `.env` file at the project root (loaded by `dotenv`).

## Design Decisions

1. **Self-contained config loading** — The `load_json_config()` function is copied into `__main__.py` rather than imported from `src/`. This means copied template tools work independently without depending on the main agent package.

2. **Parallel MCP startup** — All servers connect concurrently via `asyncio.create_task()`. Failed servers are skipped with a warning. This is the same pattern as `mcp_manager.py`.

3. **Tool catalog on startup** — All tools are discovered and printed immediately after connection. This lets you see what's available before writing your task logic.

4. **structuredContent preference** — `call_tool()` returns `structuredContent` (dict) directly when available, falling back to text. Never parse the text as JSON — if the server provides structured data, it comes through `structuredContent`.

5. **Generic LLM module** — `llm.py` is not tied to any specific use pattern. It provides both streaming (interactive) and non-streaming (batch) modes with cost tracking. Use whichever fits your task.

6. **Cost tracking built in** — Every LLM call returns a `Usage` object. Use `estimate_cost()` to convert to USD. Usage objects can be added together to track total cost across multiple calls.
