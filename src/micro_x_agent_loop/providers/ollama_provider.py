from __future__ import annotations

from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

_OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAIProvider):
    """Ollama provider — OpenAI-compatible API served locally by Ollama.

    Inherits all OpenAI logic; overrides base_url and provider name.
    Ollama does not require a real API key, but the OpenAI SDK expects
    a non-empty string, so a dummy value is used when none is supplied.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(
            api_key=api_key or "ollama",
            base_url=_OLLAMA_BASE_URL,
            provider_name="ollama",
        )
