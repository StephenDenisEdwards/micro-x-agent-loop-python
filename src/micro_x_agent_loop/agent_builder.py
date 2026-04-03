"""AgentBuilder — constructs Agent subsystems from AgentConfig.

Extracted from the monolithic ``Agent.__init__`` to give each setup
concern its own method.  Returns an ``AgentComponents`` dataclass that
Agent assigns in a slim ``__init__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from loguru import logger

from micro_x_agent_loop.agent_config import AgentConfig, LLMConfig, RoutingConfig, ToolSearchConfig
from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.app_config import resolve_runtime_env
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import SessionAccumulator
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.sub_agent import SubAgentRunner
from micro_x_agent_loop.system_prompt import get_system_prompt
from micro_x_agent_loop.system_prompt_builder import build_system_prompt
from micro_x_agent_loop.tasks.manager import TaskManager
from micro_x_agent_loop.tasks.store import TaskStore
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.tool_search import ToolSearchManager, should_activate_tool_search


@dataclass
class AgentComponents:
    """All subsystems constructed by the builder, ready for Agent to consume."""

    provider: Any
    model: str
    max_tokens: int
    temperature: float
    system_prompt: str
    tool_map: dict[str, Tool]
    converted_tools: list[dict]
    tool_search_active: bool
    tool_search_manager: ToolSearchManager | None
    autonomous: bool
    channel: Any
    line_prefix: str
    sub_agent_runner: SubAgentRunner | None
    task_manager: TaskManager | None
    compact_system_prompt: str
    max_tool_result_chars: int
    max_conversation_messages: int
    compaction_strategy: Any
    memory_enabled: bool
    memory: ActiveMemoryFacade | NullMemoryFacade
    user_memory_enabled: bool
    user_memory_dir: str
    metrics_enabled: bool
    session_accumulator: SessionAccumulator
    session_budget_usd: float
    mode_analysis_enabled: bool
    stage2_classification_enabled: bool
    stage2_model: str
    stage2_provider: Any
    working_directory: str | None
    tool_result_formatter: ToolResultFormatter
    api_payload_store: ApiPayloadStore
    semantic_routing_enabled: bool
    routing_feedback_store: Any
    task_embedding_index: object | None
    # TurnEngine construction args (routing-related)
    summarization_provider: Any
    summarization_model: str
    summarization_enabled: bool
    summarization_threshold: int
    provider_pool: Any
    semantic_classifier: Any
    routing_policies: dict
    routing_fallback_provider: str
    routing_fallback_model: str
    routing_feedback_callback: Any
    routing_confidence_threshold: float
    markdown_rendering_enabled: bool = True


def build_agent_components(config: AgentConfig) -> AgentComponents:
    """Build all Agent subsystems from config. Does not require a ``self`` reference."""
    provider = create_provider(
        config.provider, config.api_key,
        prompt_caching_enabled=config.prompt_caching_enabled,
        ollama_base_url=config.ollama_base_url,
    )
    tool_map: dict[str, Tool] = {t.name: t for t in config.tools}
    converted_tools = provider.convert_tools(config.tools)

    # --- Tool search ---
    tool_search_active = should_activate_tool_search(
        config.tool_search_enabled, converted_tools, config.model, provider=config.provider,
    )
    any_policy_needs_search = any(
        p.get("tool_search_only", False) for p in config.routing_policies.values()
    )
    ts = config.tool_search_config()
    rc = config.routing_config()
    llm = config.llm_config()

    tool_search_manager: ToolSearchManager | None = None
    if tool_search_active or any_policy_needs_search:
        embedding_index = _build_tool_embedding_index(ts)
        tool_search_manager = ToolSearchManager(
            all_tools=config.tools, converted_tools=converted_tools,
            embedding_index=embedding_index, max_load=config.tool_search_max_load,
        )
    if tool_search_active:
        logger.info(f"Tool search active: {len(config.tools)} tools deferred")

    # --- Channel & display ---
    autonomous = config.autonomous
    channel = config.channel
    line_prefix = "" if autonomous else "assistant> "
    _compact = config.provider == "ollama"

    # --- Sub-agents ---
    sub_agent_runner: SubAgentRunner | None = None
    if config.sub_agents_enabled:
        if not config.sub_agent_provider:
            raise ValueError("SubAgentProvider must be set in config when SubAgentsEnabled is true")
        if not config.sub_agent_model:
            raise ValueError("SubAgentModel must be set in config when SubAgentsEnabled is true")

    # --- System prompt ---
    system_prompt = build_system_prompt(
        base_prompt=config.system_prompt,
        tool_search_active=tool_search_active,
        ask_user_enabled=channel is not None and not _compact,
        sub_agents_enabled=config.sub_agents_enabled and not _compact,
    )

    # --- Compact system prompt + SubAgentRunner ---
    compact_system_prompt = ""
    any_policy_needs_compact = any(
        p.get("system_prompt") == "compact" for p in config.routing_policies.values()
    )
    if any_policy_needs_compact:
        compact_system_prompt = get_system_prompt(
            user_memory="", user_memory_enabled=False, concise_output_enabled=True,
            working_directory=config.working_directory, autonomous=autonomous,
            hitl_enabled=False, compact=True, tool_search_active=True,
        )
        sub_agent_runner = SubAgentRunner(
            parent_tools=config.tools, provider_name=config.provider,
            api_key=config.api_key, parent_model=config.model,
            sub_agent_provider=config.sub_agent_provider,
            sub_agent_model=config.sub_agent_model,
            timeout=config.sub_agent_timeout, max_turns=config.sub_agent_max_turns,
            max_tokens=config.sub_agent_max_tokens,
            max_tool_result_chars=config.max_tool_result_chars,
        )

    # --- Memory facade ---
    memory: ActiveMemoryFacade | NullMemoryFacade
    if config.memory_enabled and config.session_manager is not None:
        memory = ActiveMemoryFacade(
            session_manager=config.session_manager,
            checkpoint_manager=config.checkpoint_manager,
            event_emitter=config.event_emitter,
            active_session_id=config.session_id,
            store=config.memory_store,
        )
    else:
        memory = NullMemoryFacade()
        memory.active_session_id = config.session_id

    # --- Metrics ---
    session_accumulator = SessionAccumulator(session_id=config.session_id or "")

    # --- Stage-2 classification ---
    stage2_provider = (
        create_provider(config.stage2_provider, resolve_runtime_env(config.stage2_provider).provider_api_key)
        if config.stage2_classification_enabled else None
    )
    if config.stage2_classification_enabled:
        if not config.stage2_provider:
            raise ValueError("Stage2Provider must be set in config when Stage2ClassificationEnabled is true")
        if not config.stage2_model:
            raise ValueError("Stage2Model must be set in config when Stage2ClassificationEnabled is true")

    # --- Tool result summarization ---
    summarization_provider = None
    summarization_model = ""
    if config.tool_result_summarization_enabled:
        summarization_model = config.tool_result_summarization_model or config.model
        summarization_provider = create_provider(config.provider, config.api_key)

    tool_result_formatter = ToolResultFormatter(
        tool_formatting=config.tool_formatting, default_format=config.default_format,
    )

    # --- Routing ---
    provider_pool, semantic_classifier = None, None
    routing_feedback_callback = None
    routing_feedback_store = None
    task_embedding_index: object | None = None

    if config.semantic_routing_enabled:
        provider_pool, semantic_classifier, routing_feedback_store, routing_feedback_callback, task_embedding_index = (
            _build_semantic_routing(rc, llm, ts, provider)
        )

    # --- Task decomposition ---
    task_manager: TaskManager | None = None
    if config.task_decomposition_enabled:
        task_store = TaskStore(str(Path(".micro_x") / "tasks.db"))
        list_id = config.session_id or "default"
        task_manager = TaskManager(task_store, list_id)

    return AgentComponents(
        provider=provider, model=config.model, max_tokens=config.max_tokens,
        temperature=config.temperature, system_prompt=system_prompt,
        tool_map=tool_map, converted_tools=converted_tools,
        tool_search_active=tool_search_active, tool_search_manager=tool_search_manager,
        autonomous=autonomous, channel=channel, line_prefix=line_prefix,
        sub_agent_runner=sub_agent_runner, task_manager=task_manager,
        compact_system_prompt=compact_system_prompt,
        max_tool_result_chars=config.max_tool_result_chars,
        max_conversation_messages=config.max_conversation_messages,
        compaction_strategy=config.compaction_strategy,
        memory_enabled=config.memory_enabled, memory=memory,
        user_memory_enabled=config.user_memory_enabled,
        user_memory_dir=config.user_memory_dir,
        metrics_enabled=config.metrics_enabled,
        session_accumulator=session_accumulator,
        session_budget_usd=config.session_budget_usd,
        mode_analysis_enabled=config.mode_analysis_enabled,
        stage2_classification_enabled=config.stage2_classification_enabled,
        stage2_model=config.stage2_model, stage2_provider=stage2_provider,
        working_directory=config.working_directory,
        tool_result_formatter=tool_result_formatter,
        api_payload_store=ApiPayloadStore(),
        semantic_routing_enabled=config.semantic_routing_enabled,
        routing_feedback_store=routing_feedback_store,
        task_embedding_index=task_embedding_index,
        summarization_provider=summarization_provider,
        summarization_model=summarization_model,
        summarization_enabled=config.tool_result_summarization_enabled,
        summarization_threshold=config.tool_result_summarization_threshold,
        provider_pool=provider_pool, semantic_classifier=semantic_classifier,
        routing_policies=config.routing_policies,
        routing_fallback_provider=config.routing_fallback_provider or config.provider,
        routing_fallback_model=config.routing_fallback_model or config.model,
        routing_feedback_callback=routing_feedback_callback,
        routing_confidence_threshold=config.routing_confidence_threshold,
        markdown_rendering_enabled=config.markdown_rendering_enabled,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_tool_embedding_index(ts: ToolSearchConfig) -> Any:
    """Build a ToolEmbeddingIndex for semantic tool search (or None)."""
    if ts.tool_search_strategy == "keyword" or not ts.ollama_base_url:
        return None
    from micro_x_agent_loop.embedding import OllamaEmbeddingClient, ToolEmbeddingIndex
    client = OllamaEmbeddingClient(ts.ollama_base_url, ts.embedding_model)
    return ToolEmbeddingIndex(client)


def _build_semantic_routing(
    rc: RoutingConfig, llm: LLMConfig, ts: ToolSearchConfig, provider: Any,
) -> tuple[Any, Any, Any, Any, Any]:
    """Build the semantic routing subsystem. Returns (pool, classifier, feedback_store, callback, embedding_index)."""
    from micro_x_agent_loop.provider_pool import ProviderPool
    from micro_x_agent_loop.semantic_classifier import classify_task

    pool_providers: dict[str, object] = {llm.provider: provider}
    for policy in rc.routing_policies.values():
        p_name = policy.get("provider", "")
        if p_name and p_name not in pool_providers:
            try:
                p_env = resolve_runtime_env(p_name)
                pool_providers[p_name] = create_provider(
                    p_name, p_env.provider_api_key,
                    prompt_caching_enabled=llm.prompt_caching_enabled,
                    ollama_base_url=ts.ollama_base_url,
                )
            except Exception as ex:
                logger.warning(f"Failed to create provider {p_name!r} for routing: {ex}")

    provider_pool = ProviderPool(
        pool_providers, fallback_provider=rc.routing_fallback_provider or llm.provider,
    )

    task_embedding_index: object | None = None
    if ts.ollama_base_url and ts.embedding_model:
        from micro_x_agent_loop.embedding import OllamaEmbeddingClient, TaskEmbeddingIndex
        task_client = OllamaEmbeddingClient(ts.ollama_base_url, ts.embedding_model)
        task_embedding_index = TaskEmbeddingIndex(task_client)

    keywords = [kw.strip() for kw in rc.complexity_keywords.split(",") if kw.strip()]
    semantic_classifier = partial(
        classify_task, complexity_keywords=keywords,
        strategy=rc.semantic_routing_strategy,
        task_embedding_index=task_embedding_index,
    )

    routing_feedback_store = None
    routing_feedback_callback = None
    if rc.routing_feedback_enabled:
        from micro_x_agent_loop.routing_feedback import RoutingFeedbackStore
        db_path = Path(rc.routing_feedback_db_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        routing_feedback_store = RoutingFeedbackStore(str(db_path))

    logger.info(
        "Semantic routing enabled: strategy={strategy} providers={providers} policies={policies}",
        strategy=rc.semantic_routing_strategy,
        providers=list(pool_providers.keys()),
        policies=list(rc.routing_policies.keys()),
    )

    return provider_pool, semantic_classifier, routing_feedback_store, routing_feedback_callback, task_embedding_index


