"""Generic LLM helper for Anthropic Claude API.

Provides non-streaming and streaming message creation with cost tracking.
Reads ANTHROPIC_API_KEY from environment. Client is created lazily on first use.

Usage — non-streaming (batch processing):
    text, usage = await create_message(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Summarize this text: ..."}],
    )
    print(text)
    print(f"Cost: ${estimate_cost(usage):.4f}")

Usage — streaming (interactive output):
    text, usage = await stream_message(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Write a poem about coding."}],
    )
    # Text is printed to stdout in real-time during streaming.
    # 'text' contains the complete response after streaming finishes.
    print(f"\\nCost: ${estimate_cost(usage):.4f}")

Usage — cost tracking only:
    total = Usage()
    for chunk in work:
        _, usage = await create_message(...)
        total = total + usage
    print(f"Total cost: ${estimate_cost(total):.4f}")
"""

import os
from dataclasses import dataclass, field

import anthropic

# Per-token pricing (USD) as of 2025. Update as needed.
# Format: {model_prefix: (input_per_M, output_per_M, cache_write_per_M, cache_read_per_M)}
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus":   (15.0, 75.0, 18.75, 1.50),
    "claude-sonnet": (3.0,  15.0, 3.75,  0.30),
    "claude-haiku":  (0.80, 4.0,  1.0,   0.08),
}


@dataclass
class Usage:
    """Tracks token usage across one or more API calls."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    model: str = ""

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            model=self.model or other.model,
        )


def estimate_cost(usage: Usage) -> float:
    """Estimate USD cost from token usage.

    Matches the model string against known pricing prefixes (e.g.
    "claude-sonnet-4-5-20250929" matches "claude-sonnet").
    Returns 0.0 if model is unknown.
    """
    for prefix, (inp, out, cw, cr) in PRICING.items():
        if usage.model.startswith(prefix):
            return (
                usage.input_tokens * inp
                + usage.output_tokens * out
                + usage.cache_creation_input_tokens * cw
                + usage.cache_read_input_tokens * cr
            ) / 1_000_000
    return 0.0


# Lazy client — created on first API call
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or set it in your environment."
            )
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


async def create_message(
    model: str,
    max_tokens: int,
    messages: list[dict],
    *,
    system: str = "",
    temperature: float = 1.0,
) -> tuple[str, Usage]:
    """Non-streaming message creation. Good for batch/background processing.

    Args:
        model: Model ID (e.g. "claude-haiku-4-5-20251001").
        max_tokens: Maximum tokens in the response.
        messages: Conversation messages in Anthropic format.
        system: Optional system prompt.
        temperature: Sampling temperature (0.0-1.0).

    Returns:
        (response_text, usage) tuple.
    """
    client = _get_client()
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=messages,
    )
    if system:
        kwargs["system"] = system

    response = await client.messages.create(**kwargs)

    raw = response.usage
    usage = Usage(
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
        cache_creation_input_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
        model=model,
    )

    text = response.content[0].text if response.content else ""
    return text, usage


async def stream_message(
    model: str,
    max_tokens: int,
    messages: list[dict],
    *,
    system: str = "",
    temperature: float = 1.0,
) -> tuple[str, Usage]:
    """Streaming message creation. Prints text to stdout in real-time.

    Same interface as create_message() but streams output as it arrives.
    Useful for interactive/user-facing responses.

    Args:
        model: Model ID (e.g. "claude-sonnet-4-5-20250929").
        max_tokens: Maximum tokens in the response.
        messages: Conversation messages in Anthropic format.
        system: Optional system prompt.
        temperature: Sampling temperature (0.0-1.0).

    Returns:
        (complete_response_text, usage) tuple.
    """
    client = _get_client()
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=messages,
    )
    if system:
        kwargs["system"] = system

    async with client.messages.stream(**kwargs) as stream:
        async for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
        response = await stream.get_final_message()

    raw = response.usage
    usage = Usage(
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
        cache_creation_input_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
        model=model,
    )

    text = response.content[0].text if response.content else ""
    return text, usage
