# Design: Agent Loop

## Overview

The agent loop is the core runtime cycle of the application. It manages the conversation between the user, the configured LLM provider, and the tool system.

## Flow

1. User provides input (typed prompt, or finalized voice utterance from `/voice` mode)
2. Prompt is added to conversation history
3. Compaction strategy runs (may summarize old messages), then history is trimmed if still over the message limit
4. Message list is sent to the configured provider via streaming API
5. Text deltas are printed to stdout as they arrive
6. If the provider requests tool use:
   a. All tool calls execute **in parallel** via `asyncio.gather`
   b. Results are truncated if over the character limit
   c. Tool results are added to conversation history
   d. Loop back to step 3
7. If the provider returns a final text response, control returns to the REPL

## Components

### Agent

`agent.py` orchestrates the loop. Key responsibilities:

- Maintains the `_messages` list (conversation history)
- Calls `self._provider.stream_chat()` for each turn (provider-agnostic)
- Dispatches tool calls in parallel via `_execute_tools()`
- Enforces `MaxToolResultChars` truncation
- Enforces `MaxConversationMessages` trimming
- Delegates to the configured `CompactionStrategy` before trimming (see [Compaction Design](DESIGN-compaction.md))
- Routes local commands (`/help`, `/session`, `/checkpoint`, `/voice`)

### Voice Runtime

`voice_runtime.py` manages continuous voice input via MCP STT session tools:

- Starts/stops STT sessions (`stt_start_session`, `stt_stop_session`)
- Polls incremental events (`stt_get_updates`)
- Queues `utterance_final` events and forwards them into the normal `Agent.run()` path

### Provider Layer

The `LLMProvider` Protocol (`provider.py`) defines three methods:

- `stream_chat()` — streams a response, printing text deltas in real time, returns `(message_dict, tool_use_blocks, stop_reason)` in internal format
- `create_message()` — non-streaming message creation (used for compaction/summarization)
- `convert_tools()` — converts `Tool` Protocol objects to provider-specific tool schema

The `create_provider()` factory selects the implementation based on the configured `Provider` name.

**Providers:**

- `AnthropicProvider` (`providers/anthropic_provider.py`) — wraps the `anthropic` SDK, messages pass through as-is since internal format is Anthropic-native
- `OpenAIProvider` (`providers/openai_provider.py`) — translates between internal Anthropic-format messages and OpenAI chat completion format in both directions

Each provider includes its own tenacity retry targeting SDK-specific transient errors (rate limit, connection, timeout).

See [ADR-010](../architecture/decisions/ADR-010-multi-provider-llm-support.md) for the architectural decision.

### llm_client

`llm_client.py` provides shared utilities used by both providers:

- `Spinner` — thread-based spinner for real-time terminal feedback
- `_on_retry` — tenacity callback for logging retry attempts

### Conversation History

Messages accumulate in `_messages` as the conversation progresses. Each message is either:

- **User message** — the user's text input (`{"role": "user", "content": "..."}`)
- **Assistant message** — Claude's response (text + tool_use blocks)
- **Tool result message** — tool execution results (`{"role": "user", "content": [tool_result dicts]}`)

Before trimming, the agent runs its configured compaction strategy (`_maybe_compact()`). With the `"summarize"` strategy, this summarizes the middle of the conversation via an LLM call when estimated tokens exceed a threshold, preserving key context. After compaction, `_trim_conversation_history()` still runs as a hard backstop — when `len(_messages)` exceeds `MaxConversationMessages`, the oldest messages are removed from the front. A warning is printed to stderr so the user knows context was lost. See [Compaction Design](DESIGN-compaction.md) for details.

## Parallel Tool Execution

When Claude requests multiple tools in a single turn, they execute concurrently:

```python
async def _execute_tools(self, tool_use_blocks):
    async def run_one(block):
        tool = self._tool_map.get(block["name"])
        result = await tool.execute(block["input"])
        return {"type": "tool_result", "tool_use_id": block["id"], "content": result}

    results = await asyncio.gather(*(run_one(b) for b in tool_use_blocks))
    return list(results)
```

This is safe because tools are stateless and independent. The results are returned in the same order as the requests.

## Tool Result Truncation

Large tool outputs (e.g., reading a big file) can consume excessive tokens. When a result exceeds `MaxToolResultChars`:

1. The result is cut at the character limit
2. A clear message is appended: `[OUTPUT TRUNCATED: Showing X of Y characters from tool_name]`
3. A warning is printed to stderr

This ensures Claude knows the output was truncated and can request a more targeted read if needed.

## Error Handling

| Error | Handling |
|-------|----------|
| Unknown tool name | Error result returned to Claude |
| Tool raises exception | Error message returned to Claude |
| API rate limit (429) | tenacity retries with exponential backoff |
| Unrecoverable API error | Exception propagates to REPL, user sees error |

## Local Commands

Runtime local commands:

- `/help`
- `/session ...` (when memory enabled)
- `/checkpoint ...` (when memory enabled)
- `/voice start [microphone|loopback]`
- `/voice status`
- `/voice stop`
