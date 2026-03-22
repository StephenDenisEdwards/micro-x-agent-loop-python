from __future__ import annotations

from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

_OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAIProvider):
    """Ollama provider — OpenAI-compatible API served locally by Ollama.

    Inherits all OpenAI logic; overrides base_url and provider name.
    Ollama does not require a real API key, but the OpenAI SDK expects
    a non-empty string, so a dummy value is used when none is supplied.

    Differences from vanilla OpenAI handled here:
    - ``stream_options`` is omitted (not reliably supported by Ollama).
    - ``tool_choice`` is set to ``"auto"`` when tools are present, giving
      smaller models an explicit nudge to use function calling.
    """

    def __init__(self, api_key: str, base_url: str = "") -> None:
        effective_url = base_url.rstrip("/") + "/v1" if base_url else _OLLAMA_BASE_URL
        super().__init__(
            api_key=api_key or "ollama",
            base_url=effective_url,
            provider_name="ollama",
        )

    def _build_stream_kwargs(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs
