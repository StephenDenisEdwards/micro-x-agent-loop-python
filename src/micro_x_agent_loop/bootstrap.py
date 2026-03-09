from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_channel import BrokerChannel, BufferedChannel, TerminalChannel
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.app_config import AppConfig, RuntimeEnv
from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy
from micro_x_agent_loop.logging_config import setup_logging
from micro_x_agent_loop.mcp.mcp_manager import McpManager
from micro_x_agent_loop.memory import CheckpointManager, EventEmitter, MemoryStore, SessionManager, prune_memory
from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.system_prompt import get_system_prompt


@dataclass
class AppRuntime:
    agent: Agent
    mcp_manager: McpManager | None
    memory_store: MemoryStore | None
    event_sink: AsyncEventSink | None
    mcp_tools: list
    log_descriptions: list[str]


def _load_user_memory(memory_dir: Path, max_lines: int) -> str:
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        return ""
    lines = memory_file.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines])


async def bootstrap_runtime(app: AppConfig, env: RuntimeEnv, *, autonomous: bool = False) -> AppRuntime:
    log_descriptions = setup_logging(level=app.log_level, consumers=app.log_consumers)

    mcp_manager: McpManager | None = None
    tools: list = []
    if app.mcp_server_configs:
        mcp_manager = McpManager(app.mcp_server_configs)
        tools = await mcp_manager.connect_all()

    if app.compaction_strategy_name == "summarize":
        compaction_model = app.compaction_model or app.model
        compaction_strategy = SummarizeCompactionStrategy(
            provider=create_provider(app.provider_name, env.provider_api_key),
            model=compaction_model,
            threshold_tokens=app.compaction_threshold_tokens,
            protected_tail_messages=app.protected_tail_messages,
            smart_trigger_enabled=app.smart_compaction_trigger_enabled,
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
            if autonomous:
                # In --run mode, create the session if it doesn't exist yet
                active_session_id = session_manager.load_or_create(app.resume_session_id)
            else:
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

    user_memory = ""
    user_memory_dir = Path(app.user_memory_dir)
    if not user_memory_dir.is_absolute():
        user_memory_dir = Path.cwd() / user_memory_dir
    if app.user_memory_enabled:
        user_memory = _load_user_memory(user_memory_dir, app.user_memory_max_lines)

    hitl_enabled = autonomous and bool(os.environ.get("MICRO_X_BROKER_URL"))

    # Create the appropriate AgentChannel based on context
    if autonomous:
        broker_url = os.environ.get("MICRO_X_BROKER_URL")
        run_id = os.environ.get("MICRO_X_RUN_ID")
        if broker_url and run_id:
            hitl_timeout = int(os.environ.get("MICRO_X_HITL_TIMEOUT", "300"))
            channel = BrokerChannel(broker_url=broker_url, run_id=run_id, timeout=hitl_timeout)
        else:
            channel = BufferedChannel()
    else:
        channel = TerminalChannel()

    agent = Agent(
        AgentConfig(
            model=app.model,
            max_tokens=app.max_tokens,
            temperature=app.temperature,
            api_key=env.provider_api_key,
            provider=app.provider_name,
            tools=tools,
            system_prompt=get_system_prompt(
                user_memory=user_memory,
                user_memory_enabled=app.user_memory_enabled,
                concise_output_enabled=app.concise_output_enabled,
                working_directory=app.working_directory,
                autonomous=autonomous,
                hitl_enabled=hitl_enabled,
            ),
            autonomous=autonomous,
            max_tool_result_chars=app.max_tool_result_chars,
            max_conversation_messages=app.max_conversation_messages,
            compaction_strategy=compaction_strategy,
            memory_enabled=app.memory_enabled,
            session_id=active_session_id,
            session_manager=session_manager,
            checkpoint_manager=checkpoint_manager,
            event_emitter=event_emitter,
            metrics_enabled=app.metrics_enabled,
            user_memory_enabled=app.user_memory_enabled,
            user_memory_dir=str(user_memory_dir),
            prompt_caching_enabled=app.prompt_caching_enabled,
            tool_result_summarization_enabled=app.tool_result_summarization_enabled,
            tool_result_summarization_model=app.tool_result_summarization_model,
            tool_result_summarization_threshold=app.tool_result_summarization_threshold,
            mode_analysis_enabled=app.mode_analysis_enabled,
            stage2_classification_enabled=app.stage2_classification_enabled,
            stage2_model=app.stage2_model,
            tool_search_enabled=app.tool_search_enabled,
            working_directory=app.working_directory,
            tool_formatting=app.tool_formatting,
            default_format=app.default_format,
            sub_agents_enabled=app.sub_agents_enabled,
            sub_agent_model=app.sub_agent_model,
            sub_agent_timeout=app.sub_agent_timeout,
            sub_agent_max_turns=app.sub_agent_max_turns,
            sub_agent_max_tokens=app.sub_agent_max_tokens,
            channel=channel,
        )
    )

    return AppRuntime(
        agent=agent,
        mcp_manager=mcp_manager,
        memory_store=memory_store,
        event_sink=event_sink,
        mcp_tools=tools,
        log_descriptions=log_descriptions,
    )
