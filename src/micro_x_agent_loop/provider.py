from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.usage import UsageResult

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel


@runtime_checkable
class LLMProvider(Protocol):
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

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> tuple[str, UsageResult]:
        """Non-streaming message creation (used for compaction/summarization).

        Returns (text, usage).
        """
        ...

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        """Convert Tool protocol objects to provider-specific tool schema."""
        ...


def create_provider(
    provider_name: str,
    api_key: str,
    *,
    prompt_caching_enabled: bool = False,
    ollama_base_url: str = "",
) -> LLMProvider:
    """Factory: create an LLMProvider by name."""
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
