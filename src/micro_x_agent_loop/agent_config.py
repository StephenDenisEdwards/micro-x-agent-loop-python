from dataclasses import dataclass, field

from micro_x_agent_loop.tool import Tool


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 8192
    temperature: float = 1.0
    api_key: str = ""
    tools: list[Tool] = field(default_factory=list)
    system_prompt: str = ""
    max_tool_result_chars: int = 40_000
    max_conversation_messages: int = 50
    input_token_budget: int = 40_000
    tool_result_retention_chars: int = 500
