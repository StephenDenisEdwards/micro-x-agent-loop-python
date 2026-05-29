from __future__ import annotations

import re

from loguru import logger

from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

_OLLAMA_BASE_URL = "http://localhost:11434/v1"

# Matches a fenced JSON block containing a tool-call shape — emitted by
# gemma3:4b when the model wants to call a tool but skips the <tool_call>
# XML wrapper (happens when ≥15 tools are bound). Ollama does not parse
# these as tool calls, so they surface as plain text content. See plan §6.4.
_FENCED_JSON_TOOL_CALL_RE = re.compile(
    r'```(?:json)?\s*\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*"arguments"\s*:',
    re.DOTALL,
)


class OllamaProvider(OpenAIProvider):
    """Ollama provider — OpenAI-compatible API served locally by Ollama.

    Inherits all OpenAI logic; overrides base_url and provider name.
    Ollama does not require a real API key, but the OpenAI SDK expects
    a non-empty string, so a dummy value is used when none is supplied.

    Differences from vanilla OpenAI handled here:
    - ``tool_choice`` is set to ``"auto"`` when tools are present, giving
      smaller models an explicit nudge to use function calling.
    - The assembled assistant message is inspected for Gemma's known
      unparsed tool-call shapes (fenced JSON, truncated XML) so that
      ``gemma_unparsed.*`` rates are observable. See plan §4.6.
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
        kwargs = super()._build_stream_kwargs(
            model,
            max_tokens,
            temperature,
            messages,
            tools,
        )
        if tools:
            kwargs["tool_choice"] = "auto"
        return kwargs

    def _inspect_assistant_message(self, text: str, tool_calls_count: int) -> None:
        """Detect Gemma's unparsed tool-call shapes and log counter warnings.

        Only fires when the model produced text but ``tool_calls[]`` is
        empty — i.e. the model intended a tool call but Ollama could not
        parse it. Metrics only — no re-parse, no injection. The model
        retries on the next turn.
        """
        if tool_calls_count > 0 or not text:
            return
        if _FENCED_JSON_TOOL_CALL_RE.search(text):
            logger.warning(
                "gemma_unparsed.fenced_json text_len={n}",
                n=len(text),
            )
            return
        if "<tool_call>" in text and "</tool_call>" not in text:
            logger.warning(
                "gemma_unparsed.bare_xml text_len={n}",
                n=len(text),
            )
