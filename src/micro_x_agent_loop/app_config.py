from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from micro_x_agent_loop.constants import (
    DEFAULT_COMPACTION_THRESHOLD_TOKENS,
    DEFAULT_MAX_CONVERSATION_MESSAGES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_RESULT_CHARS,
    DEFAULT_MEMORY_MAX_MESSAGES_PER_SESSION,
    DEFAULT_MEMORY_MAX_SESSIONS,
    DEFAULT_MEMORY_RETENTION_DAYS,
    DEFAULT_PROTECTED_TAIL_MESSAGES,
    DEFAULT_SUBAGENT_MAX_TOKENS,
    DEFAULT_SUBAGENT_MAX_TURNS,
    DEFAULT_SUBAGENT_TIMEOUT,
    DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD,
    DEFAULT_USER_MEMORY_MAX_LINES,
)


@dataclass
class RuntimeEnv:
    provider_api_key: str
    provider_env_var: str


@dataclass
class AppConfig:
    provider_name: str
    model: str
    max_tokens: int
    temperature: float
    max_tool_result_chars: int
    max_conversation_messages: int
    compaction_strategy_name: str
    compaction_threshold_tokens: int
    protected_tail_messages: int
    working_directory: str | None
    memory_enabled: bool
    memory_db_path: str
    continue_conversation: bool
    resume_session_id: str | None
    configured_session_id: str | None
    fork_session: bool
    enable_file_checkpointing: bool
    checkpoint_write_tools_only: bool
    memory_max_sessions: int
    memory_max_messages_per_session: int
    memory_retention_days: int
    mcp_server_configs: dict
    log_level: str
    metrics_enabled: bool
    log_consumers: list | None
    user_memory_enabled: bool
    user_memory_dir: str
    user_memory_max_lines: int
    # Cost reduction
    prompt_caching_enabled: bool
    compaction_model: str
    tool_result_summarization_enabled: bool
    tool_result_summarization_model: str
    tool_result_summarization_threshold: int
    smart_compaction_trigger_enabled: bool
    concise_output_enabled: bool
    mode_analysis_enabled: bool
    stage2_classification_enabled: bool
    stage2_model: str
    tool_search_enabled: str
    # Tool result formatting
    tool_formatting: dict
    default_format: dict
    # Sub-agents
    sub_agents_enabled: bool
    sub_agent_model: str
    sub_agent_timeout: int
    sub_agent_max_turns: int
    sub_agent_max_tokens: int
    # Display
    markdown_rendering_enabled: bool


def load_json_config(config_path: str | None = None) -> tuple[dict, str]:
    """Load application config, supporting file indirection, base inheritance, and env var expansion.

    Resolution order:
    1. ``config_path`` argument (from ``--config`` CLI flag) — load directly
    2. ``ConfigFile`` field inside ``./config.json`` — resolve relative to CWD
    3. ``./config.json`` itself (backward compatible)

    After loading, if the config contains a ``Base`` key, the base config is loaded
    and merged (base values first, then variant overrides). Environment variables in
    the form ``${VAR}`` are expanded recursively in all string values.

    Returns:
        A ``(config_dict, resolved_path)`` tuple.
    """
    if config_path:
        p = Path(config_path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        with open(p) as f:
            data = json.load(f)
        data = _resolve_config_with_base(data, p.parent)
        data = _expand_env_vars(data)
        return data, str(p)

    default_path = Path.cwd() / "config.json"
    if not default_path.exists():
        return {}, "config.json (defaults)"

    with open(default_path) as f:
        data = json.load(f)

    config_file = data.get("ConfigFile")
    if config_file:
        target = Path.cwd() / config_file
        if not target.exists():
            raise FileNotFoundError(
                f"ConfigFile target not found: {target} "
                f"(referenced from config.json)"
            )
        with open(target) as f:
            data = json.load(f)
        data = _resolve_config_with_base(data, target.parent)
        data = _expand_env_vars(data)
        return data, str(config_file)

    data = _resolve_config_with_base(data, default_path.parent)
    data = _expand_env_vars(data)
    return data, "config.json"


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge *overlay* onto *base*, recursing into nested dicts.

    Overlay values win; nested dicts are merged recursively rather than replaced.
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _resolve_config_with_base(data: dict, config_dir: Path) -> dict:
    """If *data* contains a ``Base`` key, load and merge the base config first."""
    base_file = data.get("Base")
    if not base_file:
        return data

    base_path = config_dir / base_file
    if not base_path.exists():
        raise FileNotFoundError(
            f"Base config not found: {base_path} "
            f"(referenced via 'Base' key)"
        )
    with open(base_path) as f:
        base_data = json.load(f)

    # Recursively resolve the base's own Base (if any)
    base_data = _resolve_config_with_base(base_data, base_path.parent)

    # Merge: base first, overlay variant values on top
    overlay = {k: v for k, v in data.items() if k != "Base"}
    return _deep_merge(base_data, overlay)


_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(data: object) -> object:
    """Recursively expand ``${VAR}`` patterns in string values using ``os.environ``."""
    if isinstance(data, str):
        return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), data)
    if isinstance(data, dict):
        return {k: _expand_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_expand_env_vars(item) for item in data]
    return data


def _to_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Cannot interpret {value!r} as a boolean")
    return bool(value)  # int, etc. — keep Python truthiness for non-strings


def parse_app_config(config: dict) -> AppConfig:
    return AppConfig(
        provider_name=config.get("Provider", "anthropic").strip().lower(),
        model=config.get("Model", "claude-sonnet-4-5-20250929"),
        max_tokens=int(config.get("MaxTokens", DEFAULT_MAX_TOKENS)),
        temperature=float(config.get("Temperature", 0.7)),
        max_tool_result_chars=int(config.get("MaxToolResultChars", DEFAULT_MAX_TOOL_RESULT_CHARS)),
        max_conversation_messages=int(config.get("MaxConversationMessages", DEFAULT_MAX_CONVERSATION_MESSAGES)),
        compaction_strategy_name=config.get("CompactionStrategy", "none").lower(),
        compaction_threshold_tokens=int(config.get("CompactionThresholdTokens", DEFAULT_COMPACTION_THRESHOLD_TOKENS)),
        protected_tail_messages=int(config.get("ProtectedTailMessages", DEFAULT_PROTECTED_TAIL_MESSAGES)),
        working_directory=config.get("WorkingDirectory"),
        memory_enabled=_to_bool(config.get("MemoryEnabled", False), default=False),
        memory_db_path=str(config.get("MemoryDbPath", ".micro_x/memory.db")),
        continue_conversation=_to_bool(config.get("ContinueConversation", False), default=False),
        resume_session_id=str(config.get("ResumeSessionId", "")).strip() or None,
        configured_session_id=str(config.get("SessionId", "")).strip() or None,
        fork_session=_to_bool(config.get("ForkSession", False), default=False),
        enable_file_checkpointing=_to_bool(config.get("EnableFileCheckpointing", False), default=False),
        checkpoint_write_tools_only=_to_bool(config.get("CheckpointWriteToolsOnly", True), default=True),
        memory_max_sessions=int(config.get("MemoryMaxSessions", DEFAULT_MEMORY_MAX_SESSIONS)),
        memory_max_messages_per_session=int(config.get("MemoryMaxMessagesPerSession", DEFAULT_MEMORY_MAX_MESSAGES_PER_SESSION)),
        memory_retention_days=int(config.get("MemoryRetentionDays", DEFAULT_MEMORY_RETENTION_DAYS)),
        mcp_server_configs=config.get("McpServers", {}),
        metrics_enabled=_to_bool(config.get("MetricsEnabled", True), default=True),
        log_level=config.get("LogLevel", "INFO"),
        log_consumers=config.get("LogConsumers"),
        user_memory_enabled=_to_bool(config.get("UserMemoryEnabled", False), default=False),
        user_memory_dir=str(config.get("UserMemoryDir", ".micro_x/memory")),
        user_memory_max_lines=int(config.get("UserMemoryMaxLines", DEFAULT_USER_MEMORY_MAX_LINES)),
        prompt_caching_enabled=_to_bool(config.get("PromptCachingEnabled", True), default=True),
        compaction_model=str(config.get("CompactionModel", "")).strip(),
        tool_result_summarization_enabled=_to_bool(config.get("ToolResultSummarizationEnabled", False), default=False),
        tool_result_summarization_model=str(config.get("ToolResultSummarizationModel", "")).strip(),
        tool_result_summarization_threshold=int(config.get("ToolResultSummarizationThreshold", DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD)),
        smart_compaction_trigger_enabled=_to_bool(config.get("SmartCompactionTriggerEnabled", True), default=True),
        concise_output_enabled=_to_bool(config.get("ConciseOutputEnabled", False), default=False),
        mode_analysis_enabled=_to_bool(config.get("ModeAnalysisEnabled", True), default=True),
        stage2_classification_enabled=_to_bool(config.get("Stage2ClassificationEnabled", True), default=True),
        stage2_model=str(config.get("Stage2Model", "")).strip(),
        tool_search_enabled=str(config.get("ToolSearchEnabled", "false")).strip().lower(),
        tool_formatting=config.get("ToolFormatting", {}),
        default_format=config.get("DefaultFormat", {"format": "json"}),
        sub_agents_enabled=_to_bool(config.get("SubAgentsEnabled", False), default=False),
        sub_agent_model=str(config.get("SubAgentModel", "")).strip(),
        sub_agent_timeout=int(config.get("SubAgentTimeout", DEFAULT_SUBAGENT_TIMEOUT)),
        sub_agent_max_turns=int(config.get("SubAgentMaxTurns", DEFAULT_SUBAGENT_MAX_TURNS)),
        sub_agent_max_tokens=int(config.get("SubAgentMaxTokens", DEFAULT_SUBAGENT_MAX_TOKENS)),
        markdown_rendering_enabled=_to_bool(config.get("MarkdownRenderingEnabled", True), default=True),
    )


def resolve_runtime_env(provider_name: str) -> RuntimeEnv:
    if provider_name == "openai":
        provider_api_key = os.environ.get("OPENAI_API_KEY", "")
        provider_env_var = "OPENAI_API_KEY"
    else:
        provider_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        provider_env_var = "ANTHROPIC_API_KEY"

    return RuntimeEnv(
        provider_api_key=provider_api_key,
        provider_env_var=provider_env_var,
    )
