from __future__ import annotations

from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAIProvider):
    """Groq provider — OpenAI-compatible API at api.groq.com.

    Inherits all OpenAI logic; overrides base_url and provider name. Groq serves
    open-weight models (e.g. llama-3.3-70b-versatile) on LPU hardware with strong
    tool-calling reliability and a free tier. Cache-token extraction stays on the
    OpenAI-style nested field (Groq does not report prompt caching).
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key, base_url=_GROQ_BASE_URL, provider_name="groq")
