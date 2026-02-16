# ADR-003: Streaming Responses via SSE

## Status

Accepted

## Context

A non-streaming implementation would use `client.messages.create()`, which waits for the complete response before displaying anything to the user. For longer responses, this creates a noticeable delay with no feedback — the user stares at a blank prompt for several seconds.

The Anthropic Python SDK supports Server-Sent Events (SSE) streaming via `client.messages.stream()`, which yields incremental text deltas through an async context manager.

## Decision

Use `client.messages.stream()` as an async context manager. Text deltas are printed to stdout as they arrive. Tool use blocks are extracted from the final assembled message after the stream completes.

The streaming call is wrapped in the existing tenacity retry decorator. On retry, the stream restarts from scratch.

```python
async with client.messages.stream(...) as stream:
    async for event in stream:
        if event.type == "content_block_delta":
            if event.delta.type == "text_delta":
                print(event.delta.text, end="", flush=True)
    response = await stream.get_final_message()
```

## Consequences

**Easier:**
- Much better user experience — text appears word-by-word as Claude generates it
- User can see partial responses and interrupt early if the agent is going in the wrong direction
- Same tool dispatch logic works — tool blocks are collected after streaming ends

**Harder:**
- Response text is printed directly to stdout during streaming, so `Agent.run()` no longer returns a string
- `__main__` must print the `assistant>` prefix before calling `run()`
- Retry on rate limit restarts the entire stream (acceptable trade-off)
- Harder to unit test (would need to mock the async context manager)
