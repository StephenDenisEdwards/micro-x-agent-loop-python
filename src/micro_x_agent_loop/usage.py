from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UsageResult:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    duration_ms: float = 0.0
    time_to_first_token_ms: float = 0.0
    provider: str = ""
    model: str = ""
    message_count: int = 0
    tool_schema_count: int = 0
    stop_reason: str = ""


# Pricing per million tokens (USD).
# Keys: (input, output, cache_read, cache_create)
PRICING: dict[str, tuple[float, float, float, float]] = {
    # Anthropic — (input, output, cache_read, cache_write) per MTok
    "claude-opus-4-6-20260204": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-5-20250918": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-1-20250527": (15.0, 75.0, 1.50, 18.75),
    "claude-opus-4-20250514": (15.0, 75.0, 1.50, 18.75),
    "claude-sonnet-4-6-20260204": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-5-20250929": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-5-20250514": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-20250514": (3.0, 15.0, 0.30, 3.75),
    "claude-haiku-4-5-20251001": (1.0, 5.0, 0.10, 1.25),
    "claude-haiku-3-5-20241022": (0.80, 4.0, 0.08, 1.0),
    # OpenAI
    "gpt-4o": (2.50, 10.0, 1.25, 0.0),
    "gpt-4o-mini": (0.15, 0.60, 0.075, 0.0),
    "gpt-4.1": (2.0, 8.0, 0.50, 0.0),
    "gpt-4.1-mini": (0.40, 1.60, 0.10, 0.0),
    "gpt-4.1-nano": (0.10, 0.40, 0.025, 0.0),
    "o3": (2.0, 8.0, 0.50, 0.0),
    "o3-mini": (1.10, 4.40, 0.55, 0.0),
    "o4-mini": (1.10, 4.40, 0.275, 0.0),
}


def estimate_cost(usage: UsageResult) -> float:
    """Calculate estimated cost in USD from a UsageResult."""
    prices = PRICING.get(usage.model)
    if prices is None:
        return 0.0

    input_price, output_price, cache_read_price, cache_create_price = prices
    mtok = 1_000_000

    cost = (
        usage.input_tokens * input_price / mtok
        + usage.output_tokens * output_price / mtok
        + usage.cache_read_input_tokens * cache_read_price / mtok
        + usage.cache_creation_input_tokens * cache_create_price / mtok
    )
    return cost
