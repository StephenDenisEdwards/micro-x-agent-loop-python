from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from micro_x_agent_loop.compaction import CompactionStrategy, NoneCompactionStrategy
from micro_x_agent_loop.constants import (
    DEFAULT_MAX_CONVERSATION_MESSAGES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_RESULT_CHARS,
    DEFAULT_PER_TURN_ROUTING_COMPLEXITY_KEYWORDS,
    DEFAULT_PER_TURN_ROUTING_MAX_USER_CHARS,
    DEFAULT_PER_TURN_ROUTING_SHORT_FOLLOWUP_CHARS,
    DEFAULT_SESSION_BUDGET_USD,
    DEFAULT_SUBAGENT_MAX_TOKENS,
    DEFAULT_SUBAGENT_MAX_TURNS,
    DEFAULT_SUBAGENT_TIMEOUT,
    DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD,
)
from micro_x_agent_loop.memory.checkpoints import CheckpointManager
from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.tool import Tool


@dataclass
class LLMConfig:
    """Core LLM provider and model settings."""

    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.7
    api_key: str = ""
    provider: str = "anthropic"
    prompt_caching_enabled: bool = False


@dataclass
class MemoryConfig:
    """Session persistence and checkpoint settings."""

    memory_enabled: bool = False
    session_id: str | None = None
    memory_store: MemoryStore | None = None
    session_manager: SessionManager | None = None
    checkpoint_manager: CheckpointManager | None = None
    event_emitter: EventEmitter | None = None
    user_memory_enabled: bool = False
    user_memory_dir: str = ""


@dataclass
class ToolSearchConfig:
    """On-demand tool discovery settings."""

    tool_search_enabled: str = "false"
    tool_search_strategy: str = "auto"
    tool_search_max_load: int = 5
    embedding_model: str = ""
    ollama_base_url: str = ""


@dataclass
class RoutingConfig:
    """Per-turn and semantic routing settings."""

    per_turn_routing_enabled: bool = False
    per_turn_routing_model: str = ""
    per_turn_routing_provider: str = ""
    per_turn_routing_max_user_chars: int = DEFAULT_PER_TURN_ROUTING_MAX_USER_CHARS
    per_turn_routing_short_followup_chars: int = DEFAULT_PER_TURN_ROUTING_SHORT_FOLLOWUP_CHARS
    per_turn_routing_complexity_keywords: str = DEFAULT_PER_TURN_ROUTING_COMPLEXITY_KEYWORDS
    semantic_routing_enabled: bool = False
    semantic_routing_strategy: str = "rules+keywords"
    routing_policies: dict = field(default_factory=dict)
    routing_fallback_provider: str = ""
    routing_fallback_model: str = ""
    routing_confidence_threshold: float = 0.6
    routing_feedback_enabled: bool = False
    routing_feedback_db_path: str = ".micro_x/routing.db"


@dataclass
class SubAgentConfig:
    """Sub-agent spawning settings."""

    sub_agents_enabled: bool = False
    sub_agent_provider: str = ""
    sub_agent_model: str = ""
    sub_agent_timeout: int = DEFAULT_SUBAGENT_TIMEOUT
    sub_agent_max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS
    sub_agent_max_tokens: int = DEFAULT_SUBAGENT_MAX_TOKENS


@dataclass
class CostReductionConfig:
    """Cost optimisation: summarization, mode analysis, stage-2 classification."""

    tool_result_summarization_enabled: bool = False
    tool_result_summarization_model: str = ""
    tool_result_summarization_threshold: int = DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD
    mode_analysis_enabled: bool = False
    stage2_classification_enabled: bool = False
    stage2_provider: str = ""
    stage2_model: str = ""


@dataclass
class ToolResultConfig:
    """Tool result formatting and limits."""

    max_tool_result_chars: int = DEFAULT_MAX_TOOL_RESULT_CHARS
    tool_formatting: dict = field(default_factory=dict)
    default_format: dict = field(default_factory=lambda: {"format": "json"})


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.7
    api_key: str = ""
    provider: str = "anthropic"
    tools: list[Tool] = field(default_factory=list)
    system_prompt: str = ""
    max_tool_result_chars: int = DEFAULT_MAX_TOOL_RESULT_CHARS
    max_conversation_messages: int = DEFAULT_MAX_CONVERSATION_MESSAGES
    compaction_strategy: CompactionStrategy = field(default_factory=NoneCompactionStrategy)
    memory_enabled: bool = False
    session_id: str | None = None
    memory_store: MemoryStore | None = None
    session_manager: SessionManager | None = None
    checkpoint_manager: CheckpointManager | None = None
    event_emitter: EventEmitter | None = None
    metrics_enabled: bool = True
    user_memory_enabled: bool = False
    user_memory_dir: str = ""
    # Cost reduction
    prompt_caching_enabled: bool = False
    tool_result_summarization_enabled: bool = False
    tool_result_summarization_model: str = ""
    tool_result_summarization_threshold: int = DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD
    mode_analysis_enabled: bool = False
    stage2_classification_enabled: bool = False
    stage2_provider: str = ""
    stage2_model: str = ""
    tool_search_enabled: str = "false"
    tool_search_strategy: str = "auto"
    tool_search_max_load: int = 5
    embedding_model: str = ""
    ollama_base_url: str = ""
    working_directory: str | None = None
    # Tool result formatting
    tool_formatting: dict = field(default_factory=dict)
    default_format: dict = field(default_factory=lambda: {"format": "json"})
    # Autonomous mode (broker/cron runs — no human interaction)
    autonomous: bool = False
    # Sub-agents
    sub_agents_enabled: bool = False
    sub_agent_provider: str = ""
    sub_agent_model: str = ""
    sub_agent_timeout: int = DEFAULT_SUBAGENT_TIMEOUT
    sub_agent_max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS
    sub_agent_max_tokens: int = DEFAULT_SUBAGENT_MAX_TOKENS
    # Per-turn routing
    per_turn_routing_enabled: bool = False
    per_turn_routing_model: str = ""
    per_turn_routing_provider: str = ""
    per_turn_routing_max_user_chars: int = DEFAULT_PER_TURN_ROUTING_MAX_USER_CHARS
    per_turn_routing_short_followup_chars: int = DEFAULT_PER_TURN_ROUTING_SHORT_FOLLOWUP_CHARS
    per_turn_routing_complexity_keywords: str = DEFAULT_PER_TURN_ROUTING_COMPLEXITY_KEYWORDS
    # Semantic routing
    semantic_routing_enabled: bool = False
    semantic_routing_strategy: str = "rules+keywords"
    routing_policies: dict = field(default_factory=dict)
    routing_fallback_provider: str = ""
    routing_fallback_model: str = ""
    routing_confidence_threshold: float = 0.6
    routing_feedback_enabled: bool = False
    routing_feedback_db_path: str = ".micro_x/routing.db"
    # Budget
    session_budget_usd: float = DEFAULT_SESSION_BUDGET_USD
    # Display
    markdown_rendering_enabled: bool = True
    # AgentChannel for bidirectional client communication
    channel: Any = None  # AgentChannel | None (Any to avoid circular import)

    # -- Sub-config factory methods ------------------------------------------

    def llm_config(self) -> LLMConfig:
        return LLMConfig(
            model=self.model, max_tokens=self.max_tokens,
            temperature=self.temperature, api_key=self.api_key,
            provider=self.provider, prompt_caching_enabled=self.prompt_caching_enabled,
        )

    def memory_config(self) -> MemoryConfig:
        return MemoryConfig(
            memory_enabled=self.memory_enabled, session_id=self.session_id,
            memory_store=self.memory_store, session_manager=self.session_manager,
            checkpoint_manager=self.checkpoint_manager, event_emitter=self.event_emitter,
            user_memory_enabled=self.user_memory_enabled, user_memory_dir=self.user_memory_dir,
        )

    def tool_search_config(self) -> ToolSearchConfig:
        return ToolSearchConfig(
            tool_search_enabled=self.tool_search_enabled,
            tool_search_strategy=self.tool_search_strategy,
            tool_search_max_load=self.tool_search_max_load,
            embedding_model=self.embedding_model, ollama_base_url=self.ollama_base_url,
        )

    def routing_config(self) -> RoutingConfig:
        return RoutingConfig(
            per_turn_routing_enabled=self.per_turn_routing_enabled,
            per_turn_routing_model=self.per_turn_routing_model,
            per_turn_routing_provider=self.per_turn_routing_provider,
            per_turn_routing_max_user_chars=self.per_turn_routing_max_user_chars,
            per_turn_routing_short_followup_chars=self.per_turn_routing_short_followup_chars,
            per_turn_routing_complexity_keywords=self.per_turn_routing_complexity_keywords,
            semantic_routing_enabled=self.semantic_routing_enabled,
            semantic_routing_strategy=self.semantic_routing_strategy,
            routing_policies=self.routing_policies,
            routing_fallback_provider=self.routing_fallback_provider,
            routing_fallback_model=self.routing_fallback_model,
            routing_confidence_threshold=self.routing_confidence_threshold,
            routing_feedback_enabled=self.routing_feedback_enabled,
            routing_feedback_db_path=self.routing_feedback_db_path,
        )

    def sub_agent_config(self) -> SubAgentConfig:
        return SubAgentConfig(
            sub_agents_enabled=self.sub_agents_enabled,
            sub_agent_provider=self.sub_agent_provider,
            sub_agent_model=self.sub_agent_model,
            sub_agent_timeout=self.sub_agent_timeout,
            sub_agent_max_turns=self.sub_agent_max_turns,
            sub_agent_max_tokens=self.sub_agent_max_tokens,
        )

    def cost_reduction_config(self) -> CostReductionConfig:
        return CostReductionConfig(
            tool_result_summarization_enabled=self.tool_result_summarization_enabled,
            tool_result_summarization_model=self.tool_result_summarization_model,
            tool_result_summarization_threshold=self.tool_result_summarization_threshold,
            mode_analysis_enabled=self.mode_analysis_enabled,
            stage2_classification_enabled=self.stage2_classification_enabled,
            stage2_provider=self.stage2_provider, stage2_model=self.stage2_model,
        )

    def tool_result_config(self) -> ToolResultConfig:
        return ToolResultConfig(
            max_tool_result_chars=self.max_tool_result_chars,
            tool_formatting=self.tool_formatting,
            default_format=self.default_format,
        )
