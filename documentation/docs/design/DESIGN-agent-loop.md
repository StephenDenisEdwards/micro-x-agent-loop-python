# Design: Agent Loop

## Overview

The agent loop is the core runtime cycle of the application. It manages the conversation between the user, Claude, and the tool system.

## Flow

1. User types a prompt
2. Prompt is added to conversation history
3. Conversation history is trimmed if over the limit
4. Message list is sent to Claude via streaming API
5. Text deltas are printed to stdout as they arrive
6. If Claude requests tool use:
   a. All tool calls execute **in parallel** via `asyncio.gather`
   b. Results are truncated if over the character limit
   c. Tool results are added to conversation history
   d. Loop back to step 3
7. If Claude returns a final text response, control returns to the REPL

## Components

### Agent

`agent.py` orchestrates the loop. Key responsibilities:

- Maintains the `_messages` list (conversation history)
- Calls `stream_chat()` from `llm_client` for each turn
- Dispatches tool calls in parallel via `_execute_tools()`
- Enforces `MaxToolResultChars` truncation
- Enforces `MaxConversationMessages` trimming

### llm_client

`llm_client.py` handles the Anthropic API interaction:

- `stream_chat()` — streams the response, printing text deltas in real time
- tenacity `@retry` decorator wraps the function for rate limit resilience
- Returns a tuple of `(message_dict, list[tool_use_blocks])` for the agent to process

### Conversation History

Messages accumulate in `_messages` as the conversation progresses. Each message is either:

- **User message** — the user's text input (`{"role": "user", "content": "..."}`)
- **Assistant message** — Claude's response (text + tool_use blocks)
- **Tool result message** — tool execution results (`{"role": "user", "content": [tool_result dicts]}`)

When `len(_messages)` exceeds `MaxConversationMessages`, the oldest messages are removed from the front. A warning is printed to stderr so the user knows context was lost.

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
