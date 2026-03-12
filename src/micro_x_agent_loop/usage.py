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
# Format: "provider/model" → (input, output, cache_read, cache_create)
PRICING: dict[str, tuple[float, float, float, float]] = {}


def load_pricing_overrides(overrides: dict[str, dict]) -> None:
    """Load pricing data into the lookup table.

    Called once at startup from __main__.py with the config.json "Pricing" section.
    Keys are "provider/model" (e.g. "anthropic/claude-sonnet-4-6-20260204").
    Each entry: {"input": float, "output": float, "cache_read": float, "cache_create": float}
    """
    for key, prices in overrides.items():
        PRICING[key] = (
            float(prices["input"]),
            float(prices["output"]),
            float(prices.get("cache_read", 0.0)),
            float(prices.get("cache_create", 0.0)),
        )
    if PRICING:
        logger.info(f"Loaded pricing data for {len(PRICING)} model(s)")


def _lookup_pricing(provider: str, model: str) -> tuple[float, float, float, float] | None:
    """Look up pricing by provider/model, with fallback to model-only.

    Search order:
    1. Exact match on "provider/model"
    2. Prefix match on "provider/model" (e.g. 'anthropic/claude-sonnet-4-6'
       matches 'anthropic/claude-sonnet-4-6-20260204')
    3. Exact match on model portion of keys (backward compat)
    4. Prefix match on model portion of keys
    """
    qualified = f"{provider}/{model}" if provider else ""

    # 1. Exact match on provider/model
    if qualified:
        prices = PRICING.get(qualified)
        if prices is not None:
            return prices

    # 2. Prefix match on provider/model
    if qualified:
        for key, prices in PRICING.items():
            if key.startswith(qualified):
                return prices

    # 3. Exact match on model portion of keys
    for key, prices in PRICING.items():
        key_model = key.split("/", 1)[1] if "/" in key else key
        if key_model == model:
            return prices

    # 4. Prefix match on model portion of keys
    for key, prices in PRICING.items():
        key_model = key.split("/", 1)[1] if "/" in key else key
        if key_model.startswith(model):
            return prices

    return None


_warned_models: set[str] = set()


def estimate_cost(usage: UsageResult) -> float:
    """Calculate estimated cost in USD from a UsageResult."""
    prices = _lookup_pricing(usage.provider, usage.model)
    if prices is None:
        key = f"{usage.provider}/{usage.model}" if usage.provider else usage.model
        if usage.model and key not in _warned_models:
            _warned_models.add(key)
            logger.warning(
                f"No pricing data for '{key}' — cost will be reported as $0. "
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
