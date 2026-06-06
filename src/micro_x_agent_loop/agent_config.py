from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from micro_x_agent_loop.compaction import CompactionStrategy, NoneCompactionStrategy

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
    from micro_x_agent_loop.app_config import ToolResultOverride
from micro_x_agent_loop.constants import (
    DEFAULT_MAX_AGENTIC_ITERATIONS,
    DEFAULT_MAX_CONVERSATION_MESSAGES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_RESULT_CHARS,
    DEFAULT_PER_TURN_ROUTING_COMPLEXITY_KEYWORDS,
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
    max_agentic_iterations: int = DEFAULT_MAX_AGENTIC_ITERATIONS
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
    tool_result_overrides: dict[str, ToolResultOverride] = field(default_factory=dict)
    # Autonomous mode (broker/cron runs — no human interaction)
    autonomous: bool = False
    # Sub-agents
    sub_agents_enabled: bool = False
    sub_agent_provider: str = ""
    sub_agent_model: str = ""
    sub_agent_timeout: int = DEFAULT_SUBAGENT_TIMEOUT
    sub_agent_max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS
    sub_agent_max_tokens: int = DEFAULT_SUBAGENT_MAX_TOKENS
    # Routing
    complexity_keywords: str = DEFAULT_PER_TURN_ROUTING_COMPLEXITY_KEYWORDS
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
    # Task decomposition
    task_decomposition_enabled: bool = False
    # Display
    markdown_rendering_enabled: bool = True
    # AgentChannel for bidirectional client communication
    channel: AgentChannel | None = None
    # System prompt customisation (Phase 2 of PLAN-gemma-model-support)
    # `system_prompt_compact` is tri-state: None preserves the legacy fallback
    # (compact when provider == "ollama"); True/False forces it explicitly.
    # `system_prompt_extras` is appended after the core directives — used by
    # gemma3:4b to suppress over-eager tool calls on conversational turns.
    system_prompt_compact: bool | None = None
    system_prompt_extras: list[str] = field(default_factory=list)
