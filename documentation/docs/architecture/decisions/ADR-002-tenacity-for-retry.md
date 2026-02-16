# ADR-002: tenacity for API Retry Resilience

## Status

Accepted

## Context

The Anthropic API enforces rate limits (e.g., 30,000 input tokens per minute on lower tiers). When exceeded, the API returns HTTP 429 (Too Many Requests). Without retry logic, the agent fails immediately and the user must manually re-submit their prompt.

Options considered:

1. **Manual retry loop** — simple `for` loop with `asyncio.sleep`, no dependencies
2. **tenacity** — the most popular Python retry library with built-in backoff strategies
3. **backoff** — simpler alternative, less flexible than tenacity
4. **stamina** — newer library, smaller community

## Decision

Use **tenacity** with the `@retry` decorator on the `stream_chat` function. The decorator retries on `anthropic.RateLimitError` with exponential backoff.

Configuration:
- Max retries: 5
- Backoff: exponential with multiplier of 10 (10s, 20s, 40s, 80s, 160s, capped at 320s)
- Trigger: `anthropic.RateLimitError`
- User feedback: retry attempts printed to stderr via `before_sleep` callback
- `reraise=True` — if all retries are exhausted, the original exception is raised

```python
@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=10, min=10, max=320),
    stop=stop_after_attempt(5),
    before_sleep=_on_retry,
    reraise=True,
)
async def stream_chat(...):
```

## Consequences

**Easier:**
- Rate limit errors recover automatically without user intervention
- tenacity's decorator API is clean and readable
- Can extend with additional retry conditions or callbacks later
- Works seamlessly with async functions

**Harder:**
- Additional pip dependency
- Long waits on repeated rate limits (up to ~5 minutes total backoff)
- Retry wraps the entire streaming call; a partial stream followed by a 429 would restart from scratch
