from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


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
# Loaded at startup from config.json "Pricing" key via load_pricing_overrides().
# Format: model_id → (input, output, cache_read, cache_create)
PRICING: dict[str, tuple[float, float, float, float]] = {}


def load_pricing_overrides(overrides: dict[str, dict]) -> None:
    """Load pricing data into the lookup table.

    Called once at startup from __main__.py with the config.json "Pricing" section.
    Each entry: {"input": float, "output": float, "cache_read": float, "cache_create": float}
    """
    for model, prices in overrides.items():
        PRICING[model] = (
            float(prices["input"]),
            float(prices["output"]),
            float(prices.get("cache_read", 0.0)),
            float(prices.get("cache_create", 0.0)),
        )
    if PRICING:
        logger.info(f"Loaded pricing data for {len(PRICING)} model(s)")


def _lookup_pricing(model: str) -> tuple[float, float, float, float] | None:
    """Look up pricing by exact match, then prefix match (e.g. 'claude-sonnet-4-6'
    matches 'claude-sonnet-4-6-20260204')."""
    prices = PRICING.get(model)
    if prices is not None:
        return prices
    for key, prices in PRICING.items():
        if key.startswith(model):
            return prices
    return None


_warned_models: set[str] = set()


def estimate_cost(usage: UsageResult) -> float:
    """Calculate estimated cost in USD from a UsageResult."""
    prices = _lookup_pricing(usage.model)
    if prices is None:
        if usage.model and usage.model not in _warned_models:
            _warned_models.add(usage.model)
            logger.warning(
                f"No pricing data for model '{usage.model}' — cost will be reported as $0. "
                f"Add it to the Pricing section in config.json."
            )
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
