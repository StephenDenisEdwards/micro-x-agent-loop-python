from __future__ import annotations

from typing import Any

from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider — OpenAI-compatible API at api.deepseek.com.

    Inherits all OpenAI logic; overrides base_url, provider name, and
    cache-token extraction (DeepSeek uses prompt_cache_hit_tokens at the
    top level, not nested under prompt_tokens_details).
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key, base_url=_DEEPSEEK_BASE_URL, provider_name="deepseek")

    def _extract_cached_tokens(self, usage: Any) -> int:
        # DeepSeek returns cache hits as a top-level field, not nested.
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        if hit is not None:
            return int(hit)
        # Fall back to OpenAI-style nested field (future-proofing).
        return super()._extract_cached_tokens(usage)
