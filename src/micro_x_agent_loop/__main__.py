import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy
from micro_x_agent_loop.llm_client import create_client
from micro_x_agent_loop.logging_config import setup_logging
from micro_x_agent_loop.memory import (
    CheckpointManager,
    EventEmitter,
    MemoryStore,
    SessionManager,
    prune_memory,
)
from micro_x_agent_loop.system_prompt import get_system_prompt
from micro_x_agent_loop.mcp.mcp_manager import McpManager
from micro_x_agent_loop.tool_registry import get_all


def load_config() -> dict:
    # Look for config.json in the current working directory (where run.bat runs from)
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


async def main() -> None:
    load_dotenv()

    config = load_config()

    log_descriptions = setup_logging(
        level=config.get("LogLevel", "INFO"),
        consumers=config.get("LogConsumers"),
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable is required.")
        sys.exit(1)

    model = config.get("Model", "claude-sonnet-4-5-20250929")
    max_tokens = int(config.get("MaxTokens", 8192))
    temperature = float(config.get("Temperature", 1.0))
    max_tool_result_chars = int(config.get("MaxToolResultChars", 40_000))
    max_conversation_messages = int(config.get("MaxConversationMessages", 50))
    compaction_strategy_name = config.get("CompactionStrategy", "none").lower()
    compaction_threshold_tokens = int(config.get("CompactionThresholdTokens", 80_000))
    protected_tail_messages = int(config.get("ProtectedTailMessages", 6))
    working_directory = config.get("WorkingDirectory")
    google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    anthropic_admin_api_key = os.environ.get("ANTHROPIC_ADMIN_API_KEY")
    brave_api_key = os.environ.get("BRAVE_API_KEY")
    memory_enabled = _to_bool(config.get("MemoryEnabled", False), default=False)
    memory_db_path = str(config.get("MemoryDbPath", ".micro_x/memory.db"))
    continue_conversation = _to_bool(config.get("ContinueConversation", False), default=False)
    resume_session_id = str(config.get("ResumeSessionId", "")).strip() or None
    configured_session_id = str(config.get("SessionId", "")).strip() or None
    fork_session = _to_bool(config.get("ForkSession", False), default=False)
    enable_file_checkpointing = _to_bool(config.get("EnableFileCheckpointing", False), default=False)
    checkpoint_write_tools_only = _to_bool(config.get("CheckpointWriteToolsOnly", True), default=True)
    memory_max_sessions = int(config.get("MemoryMaxSessions", 200))
    memory_max_messages_per_session = int(config.get("MemoryMaxMessagesPerSession", 5000))
    memory_retention_days = int(config.get("MemoryRetentionDays", 30))

    tools = get_all(working_directory, google_client_id, google_client_secret, anthropic_admin_api_key, brave_api_key)

    mcp_manager: McpManager | None = None
    mcp_tools: list = []
    mcp_server_configs = config.get("McpServers", {})
    if mcp_server_configs:
        mcp_manager = McpManager(mcp_server_configs)
        mcp_tools = await mcp_manager.connect_all()
        tools.extend(mcp_tools)

    if compaction_strategy_name == "summarize":
        compaction_strategy = SummarizeCompactionStrategy(
            client=create_client(api_key),
            model=model,
            threshold_tokens=compaction_threshold_tokens,
            protected_tail_messages=protected_tail_messages,
        )
    else:
        compaction_strategy = NoneCompactionStrategy()

    memory_store: MemoryStore | None = None
    event_emitter: EventEmitter | None = None
    session_manager: SessionManager | None = None
    checkpoint_manager: CheckpointManager | None = None
    active_session_id: str | None = None

    if memory_enabled:
        db_path = Path(memory_db_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        memory_store = MemoryStore(str(db_path))
        event_emitter = EventEmitter(memory_store)
        session_manager = SessionManager(memory_store, model, event_emitter)
        checkpoint_manager = CheckpointManager(
            memory_store,
            event_emitter,
            working_directory=working_directory,
            enabled=enable_file_checkpointing,
            write_tools_only=checkpoint_write_tools_only,
        )
        prune_memory(
            memory_store,
            max_sessions=memory_max_sessions,
            max_messages_per_session=memory_max_messages_per_session,
            retention_days=memory_retention_days,
        )

        if resume_session_id:
            if session_manager.get_session(resume_session_id) is None:
                logger.error(f"Resume session not found: {resume_session_id}")
                sys.exit(1)
            active_session_id = resume_session_id
        elif continue_conversation and configured_session_id:
            active_session_id = session_manager.load_or_create(configured_session_id)
        else:
            active_session_id = session_manager.create_session()

        if fork_session:
            active_session_id = session_manager.fork_session(active_session_id)

    agent = Agent(
        AgentConfig(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=api_key,
            tools=tools,
            system_prompt=get_system_prompt(),
            max_tool_result_chars=max_tool_result_chars,
            max_conversation_messages=max_conversation_messages,
            compaction_strategy=compaction_strategy,
            memory_enabled=memory_enabled,
            session_id=active_session_id,
            session_manager=session_manager,
            checkpoint_manager=checkpoint_manager,
            event_emitter=event_emitter,
        )
    )
    await agent.initialize_session()

    print("micro-x-agent-loop (type 'exit' to quit, '/help' for commands)")
    builtin_tools = [t for t in tools if t not in mcp_tools]
    print("Tools:")
    for t in builtin_tools:
        print(f"  - {t.name}")
    if mcp_tools:
        mcp_names: dict[str, list[str]] = {}
        for t in mcp_tools:
            server, _, tool_name = t.name.partition("__")
            mcp_names.setdefault(server, []).append(tool_name or t.name)
        print("MCP servers:")
        for server, tool_names in mcp_names.items():
            print(f"  - {server}: {', '.join(tool_names)}")
    if working_directory:
        print(f"Working directory: {working_directory}")
    if compaction_strategy_name != "none":
        print(f"Compaction: {compaction_strategy_name} (threshold: {compaction_threshold_tokens:,} tokens, tail: {protected_tail_messages} messages)")
    if memory_enabled:
        print(f"Memory: enabled (session: {active_session_id})")
        print(
            "Memory controls: /session, /session list [limit], /session name <title>, "
            "/session resume <id>, /session fork, /checkpoint list [limit], /checkpoint rewind <id>"
        )
    if log_descriptions:
        print(f"Logging: {', '.join(log_descriptions)}")
    print()

    try:
        while True:
            try:
                user_input = input("you> ")
            except (EOFError, KeyboardInterrupt):
                break

            trimmed = user_input.strip()

            if trimmed in ("exit", "quit"):
                break

            if not trimmed:
                continue

            try:
                print()  # newline before spinner
                await agent.run(trimmed)
                print("\n")
            except Exception as ex:
                logger.error(f"Unhandled error: {ex}")
    finally:
        if mcp_manager:
            await mcp_manager.close()
        if memory_store:
            memory_store.close()


def _install_transport_cleanup_hook() -> None:
    """Suppress 'unclosed transport' noise from asyncio subprocess cleanup on Windows.

    When MCP stdio servers shut down, asyncio's proactor transport __del__ methods
    fire after pipes are already closed, producing ugly but harmless tracebacks.
    """
    _default_hook = sys.unraisablehook

    def _hook(unraisable) -> None:
        obj_str = str(unraisable.object) if unraisable.object is not None else ""
        if "Transport" in obj_str and isinstance(unraisable.exc_value, (ResourceWarning, ValueError)):
            return  # suppress
        _default_hook(unraisable)

    sys.unraisablehook = _hook


if __name__ == "__main__":
    _install_transport_cleanup_hook()
    asyncio.run(main())
