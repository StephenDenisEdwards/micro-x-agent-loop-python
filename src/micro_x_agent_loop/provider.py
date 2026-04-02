from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.usage import UsageResult

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel


@runtime_checkable
class LLMCompactor(Protocol):
    """Narrow protocol for non-streaming message creation (compaction, summarization, classification)."""

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> tuple[str, UsageResult]:
        """Non-streaming message creation. Returns (text, usage)."""
        ...


@runtime_checkable
class LLMProvider(LLMCompactor, Protocol):
    """Full LLM provider capable of streaming chat and tool use."""

    @property
    def family(self) -> str:
        """Provider family for format-compatible fallback grouping.

        Providers in the same family share message/tool wire formats.
        Values: 'anthropic', 'openai', 'gemini'.
        """
        ...

    async def stream_chat(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        *,
        channel: AgentChannel | None = None,
    ) -> tuple[dict, list[dict], str, UsageResult]:
        """Stream a chat response, printing text deltas to stdout in real time.

        Returns (message_dict, tool_use_blocks, stop_reason, usage) in Anthropic-style
        internal format.
        """
        ...

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        """Convert Tool protocol objects to provider-specific tool schema."""
        ...


class ProviderFactory:
    """Centralised LLM provider creation with automatic API key resolution.

    Caches shared config (prompt caching, Ollama URL) so callers only need
    to specify the provider name. API keys are resolved from environment
    variables via ``resolve_runtime_env`` when not supplied explicitly.
    """

    def __init__(
        self,
        *,
        default_api_key: str = "",
        default_provider: str = "",
        prompt_caching_enabled: bool = False,
        ollama_base_url: str = "",
    ) -> None:
        self._default_api_key = default_api_key
        self._default_provider = default_provider
        self._prompt_caching_enabled = prompt_caching_enabled
        self._ollama_base_url = ollama_base_url

    def create(
        self,
        provider_name: str,
        api_key: str = "",
        *,
        prompt_caching_enabled: bool | None = None,
    ) -> LLMProvider:
        """Create a provider, resolving the API key from env if not supplied."""
        if not api_key:
            if provider_name == self._default_provider and self._default_api_key:
                api_key = self._default_api_key
            else:
                from micro_x_agent_loop.app_config import resolve_runtime_env
                api_key = resolve_runtime_env(provider_name).provider_api_key
        caching = prompt_caching_enabled if prompt_caching_enabled is not None else self._prompt_caching_enabled
        return create_provider(
            provider_name, api_key,
            prompt_caching_enabled=caching,
            ollama_base_url=self._ollama_base_url,
        )


def create_provider(
    provider_name: str,
    api_key: str,
    *,
    prompt_caching_enabled: bool = False,
    ollama_base_url: str = "",
) -> LLMProvider:
    """Low-level factory: create an LLMProvider by name. Prefer ``ProviderFactory.create()``."""
    name = provider_name.strip().lower()
    if name == "anthropic":
        from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key, prompt_caching_enabled=prompt_caching_enabled)
    if name == "openai":
        from micro_x_agent_loop.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key)
    if name == "deepseek":
        from micro_x_agent_loop.providers.deepseek_provider import DeepSeekProvider
        return DeepSeekProvider(api_key)
    if name == "gemini":
        from micro_x_agent_loop.providers.gemini_provider import GeminiProvider
        return GeminiProvider(api_key)
    if name == "ollama":
        from micro_x_agent_loop.providers.ollama_provider import OllamaProvider
        return OllamaProvider(api_key, base_url=ollama_base_url)
    raise ValueError(
        f"Unknown provider: {provider_name!r}. Supported: 'anthropic', 'openai', 'deepseek', 'gemini', 'ollama'",
    )
