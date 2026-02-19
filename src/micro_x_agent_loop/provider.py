from typing import Protocol, runtime_checkable

from micro_x_agent_loop.tool import Tool


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
        line_prefix: str = "",
    ) -> tuple[dict, list[dict], str]:
        """Stream a chat response, printing text deltas to stdout in real time.

        Returns (message_dict, tool_use_blocks, stop_reason) in Anthropic-style
        internal format.
        """
        ...

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> str:
        """Non-streaming message creation (used for compaction/summarization)."""
        ...

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        """Convert Tool protocol objects to provider-specific tool schema."""
        ...


def create_provider(provider_name: str, api_key: str) -> LLMProvider:
    """Factory: create an LLMProvider by name."""
    name = provider_name.strip().lower()
    if name == "anthropic":
        from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key)
    if name == "openai":
        from micro_x_agent_loop.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key)
    raise ValueError(f"Unknown provider: {provider_name!r}. Supported: 'anthropic', 'openai'")
