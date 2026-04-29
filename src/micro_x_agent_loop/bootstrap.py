from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_channel import BrokerChannel, BufferedChannel, TerminalChannel
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.app_config import AppConfig, RuntimeEnv, resolve_runtime_env
from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy
from micro_x_agent_loop.logging_config import setup_logging
from micro_x_agent_loop.manifest import load_manifest
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


def _resolve_session(
    session_manager: SessionManager,
    app: AppConfig,
    *,
    autonomous: bool = False,
) -> str:
    """Determine which session to use: resume, continue, new, or fork."""
    if app.resume_session_id:
        if autonomous:
            active = session_manager.load_or_create(app.resume_session_id)
        else:
            resolved = session_manager.resolve_session_identifier(app.resume_session_id)
            if resolved is None:
                raise ValueError(f"Resume session not found: {app.resume_session_id}")
            active = resolved["id"]
    elif app.continue_conversation and app.configured_session_id:
        active = session_manager.load_or_create(app.configured_session_id)
    else:
        active = session_manager.create_session()

    if app.fork_session and active is not None:
        active = session_manager.fork_session(active)

    return active


async def bootstrap_runtime(
    app: AppConfig,
    env: RuntimeEnv,
    *,
    autonomous: bool = False,
    resolved_config: dict[str, Any] | None = None,
    channel_override: Any = None,
) -> AppRuntime:
    log_descriptions = setup_logging(level=app.log_level, consumers=app.log_consumers)

    mcp_manager: McpManager | None = None
    tools: list = []
    if app.mcp_server_configs:
        mcp_manager = McpManager(app.mcp_server_configs)
        tools = await mcp_manager.connect_all()

    # Load manifest tools (generated MCP servers from tools/manifest.json).
    # These connect on-demand when first called, not at startup.
    project_root = Path.cwd()
    if mcp_manager is None:
        mcp_manager = McpManager({})
    manifest_tools = load_manifest(
        project_root,
        connect_fn=mcp_manager.connect_on_demand,
        resolved_config=resolved_config,
    )
    tools.extend(manifest_tools)

    compaction_strategy: SummarizeCompactionStrategy | NoneCompactionStrategy
    if app.compaction_strategy_name == "summarize":
        if not app.compaction_provider:
            raise ValueError("CompactionProvider must be set in config when CompactionStrategy is 'summarize'")
        if not app.compaction_model:
            raise ValueError("CompactionModel must be set in config when CompactionStrategy is 'summarize'")
        compaction_env = (
            resolve_runtime_env(app.compaction_provider) if app.compaction_provider != app.provider_name else env
        )
        compaction_strategy = SummarizeCompactionStrategy(
            provider=create_provider(app.compaction_provider, compaction_env.provider_api_key),
            model=app.compaction_model,
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

        active_session_id = _resolve_session(
            session_manager,
            app,
            autonomous=autonomous,
        )

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
    channel: Any  # AgentChannel
    if channel_override is not None:
        channel = channel_override
    elif autonomous:
        broker_url = os.environ.get("MICRO_X_BROKER_URL")
        run_id = os.environ.get("MICRO_X_RUN_ID")
        if broker_url and run_id:
            hitl_timeout = int(os.environ.get("MICRO_X_HITL_TIMEOUT", "300"))
            channel = BrokerChannel(broker_url=broker_url, run_id=run_id, timeout=hitl_timeout)
        else:
            channel = BufferedChannel()
    else:
        channel = TerminalChannel(markdown=app.markdown_rendering_enabled)

    # Build routing policies dict with resolved provider/model references
    routing_policies = dict(app.routing_policies) if app.routing_policies else {}

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
                task_decomposition_enabled=app.task_decomposition_enabled,
                working_directory=app.working_directory,
                autonomous=autonomous,
                hitl_enabled=hitl_enabled,
                compact=app.provider_name == "ollama",
            ),
            autonomous=autonomous,
            max_tool_result_chars=app.max_tool_result_chars,
            max_conversation_messages=app.max_conversation_messages,
            compaction_strategy=compaction_strategy,
            memory_enabled=app.memory_enabled,
            memory_store=memory_store,
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
            tool_result_overrides=app.tool_result_overrides,
            mode_analysis_enabled=app.mode_analysis_enabled,
            stage2_classification_enabled=app.stage2_classification_enabled,
            stage2_provider=app.stage2_provider,
            stage2_model=app.stage2_model,
            tool_search_enabled=app.tool_search_enabled,
            tool_search_strategy=app.tool_search_strategy,
            tool_search_max_load=app.tool_search_max_load,
            embedding_model=app.embedding_model,
            ollama_base_url=app.ollama_base_url,
            working_directory=app.working_directory,
            tool_formatting=app.tool_formatting,
            default_format=app.default_format,
            sub_agents_enabled=app.sub_agents_enabled,
            sub_agent_provider=app.sub_agent_provider,
            sub_agent_model=app.sub_agent_model,
            sub_agent_timeout=app.sub_agent_timeout,
            sub_agent_max_turns=app.sub_agent_max_turns,
            sub_agent_max_tokens=app.sub_agent_max_tokens,
            complexity_keywords=app.complexity_keywords,
            semantic_routing_enabled=app.semantic_routing_enabled,
            semantic_routing_strategy=app.semantic_routing_strategy,
            routing_policies=routing_policies,
            routing_fallback_provider=app.routing_fallback_provider or app.provider_name,
            routing_fallback_model=app.routing_fallback_model or app.model,
            routing_feedback_enabled=app.routing_feedback_enabled,
            routing_feedback_db_path=app.routing_feedback_db_path,
            task_decomposition_enabled=app.task_decomposition_enabled,
            session_budget_usd=app.session_budget_usd,
            channel=channel,
        )
    )

    # Initialize embedding indices (async, may take 1-2s each)
    await agent.initialize_tool_search_embeddings()
    await agent.initialize_task_embeddings()

    return AppRuntime(
        agent=agent,
        mcp_manager=mcp_manager,
        memory_store=memory_store,
        event_sink=event_sink,
        mcp_tools=tools,
        log_descriptions=log_descriptions,
    )
