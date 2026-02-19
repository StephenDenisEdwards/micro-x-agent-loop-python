from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RuntimeEnv:
    provider_api_key: str
    provider_env_var: str
    google_client_id: str | None
    google_client_secret: str | None
    anthropic_admin_api_key: str | None
    brave_api_key: str | None
    github_token: str | None


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
    log_consumers: list | None


def load_json_config() -> dict:
    config_path = Path.cwd() / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


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
    return bool(value)


def parse_app_config(config: dict) -> AppConfig:
    return AppConfig(
        provider_name=config.get("Provider", "anthropic").strip().lower(),
        model=config.get("Model", "claude-sonnet-4-5-20250929"),
        max_tokens=int(config.get("MaxTokens", 8192)),
        temperature=float(config.get("Temperature", 1.0)),
        max_tool_result_chars=int(config.get("MaxToolResultChars", 40_000)),
        max_conversation_messages=int(config.get("MaxConversationMessages", 50)),
        compaction_strategy_name=config.get("CompactionStrategy", "none").lower(),
        compaction_threshold_tokens=int(config.get("CompactionThresholdTokens", 80_000)),
        protected_tail_messages=int(config.get("ProtectedTailMessages", 6)),
        working_directory=config.get("WorkingDirectory"),
        memory_enabled=_to_bool(config.get("MemoryEnabled", False), default=False),
        memory_db_path=str(config.get("MemoryDbPath", ".micro_x/memory.db")),
        continue_conversation=_to_bool(config.get("ContinueConversation", False), default=False),
        resume_session_id=str(config.get("ResumeSessionId", "")).strip() or None,
        configured_session_id=str(config.get("SessionId", "")).strip() or None,
        fork_session=_to_bool(config.get("ForkSession", False), default=False),
        enable_file_checkpointing=_to_bool(config.get("EnableFileCheckpointing", False), default=False),
        checkpoint_write_tools_only=_to_bool(config.get("CheckpointWriteToolsOnly", True), default=True),
        memory_max_sessions=int(config.get("MemoryMaxSessions", 200)),
        memory_max_messages_per_session=int(config.get("MemoryMaxMessagesPerSession", 5000)),
        memory_retention_days=int(config.get("MemoryRetentionDays", 30)),
        mcp_server_configs=config.get("McpServers", {}),
        log_level=config.get("LogLevel", "INFO"),
        log_consumers=config.get("LogConsumers"),
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
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        anthropic_admin_api_key=os.environ.get("ANTHROPIC_ADMIN_API_KEY"),
        brave_api_key=os.environ.get("BRAVE_API_KEY"),
        github_token=os.environ.get("GITHUB_TOKEN"),
    )
