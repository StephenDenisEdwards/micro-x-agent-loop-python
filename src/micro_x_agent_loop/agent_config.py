from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from micro_x_agent_loop.compaction import CompactionStrategy, NoneCompactionStrategy
from micro_x_agent_loop.constants import (
    DEFAULT_MAX_CONVERSATION_MESSAGES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_RESULT_CHARS,
    DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD,
)
from micro_x_agent_loop.memory.checkpoints import CheckpointManager
from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
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
    compaction_strategy: CompactionStrategy = field(default_factory=NoneCompactionStrategy)
    memory_enabled: bool = False
    session_id: str | None = None
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
    stage2_model: str = ""  # empty = use main model
    tool_search_enabled: str = "false"
    working_directory: str | None = None
    # Tool result formatting
    tool_formatting: dict = field(default_factory=dict)
    default_format: dict = field(default_factory=lambda: {"format": "json"})
    # Autonomous mode (broker/cron runs — no human interaction)
    autonomous: bool = False
    # AgentChannel for bidirectional client communication
    channel: Any = None  # AgentChannel | None (Any to avoid circular import)
