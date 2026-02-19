from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.app_config import AppConfig, RuntimeEnv
from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy
from micro_x_agent_loop.logging_config import setup_logging
from micro_x_agent_loop.mcp.mcp_manager import McpManager
from micro_x_agent_loop.memory import CheckpointManager, EventEmitter, MemoryStore, SessionManager, prune_memory
from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.system_prompt import get_system_prompt
from micro_x_agent_loop.tool_registry import get_all


@dataclass
class AppRuntime:
    agent: Agent
    mcp_manager: McpManager | None
    memory_store: MemoryStore | None
    event_sink: AsyncEventSink | None
    builtin_tools: list
    mcp_tools: list
    log_descriptions: list[str]


async def bootstrap_runtime(app: AppConfig, env: RuntimeEnv) -> AppRuntime:
    log_descriptions = setup_logging(level=app.log_level, consumers=app.log_consumers)

    tools = get_all(
        app.working_directory,
        env.google_client_id,
        env.google_client_secret,
        env.anthropic_admin_api_key,
        env.brave_api_key,
        env.github_token,
    )

    mcp_manager: McpManager | None = None
    mcp_tools: list = []
    if app.mcp_server_configs:
        mcp_manager = McpManager(app.mcp_server_configs)
        mcp_tools = await mcp_manager.connect_all()
        tools.extend(mcp_tools)

    if app.compaction_strategy_name == "summarize":
        compaction_strategy = SummarizeCompactionStrategy(
            provider=create_provider(app.provider_name, env.provider_api_key),
            model=app.model,
            threshold_tokens=app.compaction_threshold_tokens,
            protected_tail_messages=app.protected_tail_messages,
        )
    else:
        compaction_strategy = NoneCompactionStrategy()

    memory_store: MemoryStore | None = None
    event_sink: AsyncEventSink | None = None
    event_emitter: EventEmitter | None = None
    session_manager: SessionManager | None = None
    checkpoint_manager: CheckpointManager | None = None
    active_session_id: str | None = None

    if app.memory_enabled:
        db_path = Path(app.memory_db_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        memory_store = MemoryStore(str(db_path))
        event_sink = AsyncEventSink(memory_store)
        await event_sink.start()
        event_emitter = EventEmitter(memory_store, sink=event_sink)
        session_manager = SessionManager(memory_store, app.model, event_emitter)
        checkpoint_manager = CheckpointManager(
            memory_store,
            event_emitter,
            working_directory=app.working_directory,
            enabled=app.enable_file_checkpointing,
            write_tools_only=app.checkpoint_write_tools_only,
        )

        if app.resume_session_id:
            resolved = session_manager.resolve_session_identifier(app.resume_session_id)
            if resolved is None:
                raise ValueError(f"Resume session not found: {app.resume_session_id}")
            active_session_id = resolved["id"]
        elif app.continue_conversation and app.configured_session_id:
            active_session_id = session_manager.load_or_create(app.configured_session_id)
        else:
            active_session_id = session_manager.create_session()

        if app.fork_session and active_session_id is not None:
            active_session_id = session_manager.fork_session(active_session_id)

        prune_memory(
            memory_store,
            max_sessions=app.memory_max_sessions,
            max_messages_per_session=app.memory_max_messages_per_session,
            retention_days=app.memory_retention_days,
        )

    agent = Agent(
        AgentConfig(
            model=app.model,
            max_tokens=app.max_tokens,
            temperature=app.temperature,
            api_key=env.provider_api_key,
            provider=app.provider_name,
            tools=tools,
            system_prompt=get_system_prompt(),
            max_tool_result_chars=app.max_tool_result_chars,
            max_conversation_messages=app.max_conversation_messages,
            compaction_strategy=compaction_strategy,
            memory_enabled=app.memory_enabled,
            session_id=active_session_id,
            session_manager=session_manager,
            checkpoint_manager=checkpoint_manager,
            event_emitter=event_emitter,
        )
    )

    return AppRuntime(
        agent=agent,
        mcp_manager=mcp_manager,
        memory_store=memory_store,
        event_sink=event_sink,
        builtin_tools=[t for t in tools if t not in mcp_tools],
        mcp_tools=mcp_tools,
        log_descriptions=log_descriptions,
    )
