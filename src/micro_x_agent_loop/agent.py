from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.commands.command_handler import CommandHandler
from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore
from micro_x_agent_loop.commands.router import CommandRouter
from micro_x_agent_loop.compaction import SummarizeCompactionStrategy
from micro_x_agent_loop.constants import MAX_TOKENS_RETRIES, SESSION_BUDGET_WARN_THRESHOLD
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import (
    SessionAccumulator,
    build_api_call_error_metric,
    build_api_call_metric,
    build_compaction_metric,
    build_session_summary_metric,
    build_tool_execution_metric,
    metrics_jsonl_subscriber,
)
from micro_x_agent_loop.mode_selector import (
    ModeAnalysis,
    RecommendedMode,
    Stage2Result,
    analyze_prompt,
    build_stage2_prompt,
    format_analysis,
    parse_stage2_response,
)
from micro_x_agent_loop.observability import ObservabilityEmitter, config_hash, resolve_code_sha
from micro_x_agent_loop.routing_feedback import make_routing_outcome_subscriber
from micro_x_agent_loop.routing_strategy import RoutingDecision
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult, estimate_cost
from micro_x_agent_loop.voice_runtime import VoiceRuntime


def _is_safe_message_head(msg: dict) -> bool:
    """True if ``msg`` can safely sit at ``messages[0]`` of an Anthropic request:
    role is ``user`` and content is not solely ``tool_result`` blocks (whose
    matching ``tool_use`` would have been trimmed away).
    """
    if msg.get("role") != "user":
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") != "tool_result" for b in content)


def _find_safe_trim_count(messages: list[dict], max_messages: int) -> int:
    """Return how many leading messages can be dropped to bring the list to
    at most ``max_messages`` without leaving an orphan ``tool_result`` at the
    head. Returns 0 when no safe boundary exists in the trim range.
    """
    if max_messages <= 0 or len(messages) <= max_messages:
        return 0
    target = len(messages) - max_messages
    safe = target
    while safe < len(messages) and not _is_safe_message_head(messages[safe]):
        safe += 1
    if safe >= len(messages):
        return 0
    return safe


def _repair_orphan_head(messages: list[dict]) -> tuple[list[dict], int]:
    """Drop leading messages from ``messages`` until the head is safe to send
    to Anthropic. Returns ``(repaired, dropped_count)``. Used after loading a
    persisted session that may have been corrupted by older trim logic.
    """
    drop = 0
    while drop < len(messages) and not _is_safe_message_head(messages[drop]):
        drop += 1
    if drop == 0:
        return messages, 0
    return messages[drop:], drop


_INTERRUPTED_TOOL_RESULT = (
    "Tool execution did not complete (interrupted, cancelled, or crashed). "
    "No result is available."
)


def _find_tail_orphan_tool_use_ids(messages: list[dict]) -> list[str]:
    """Return any ``tool_use`` ids in the LAST message that lack a matching
    ``tool_result`` afterwards. The "tail orphan" pattern is the typical
    fallout from cancelling a run mid-tool: the assistant ``tool_use`` was
    appended, then tool execution was cancelled before the user
    ``tool_result`` could be appended.
    """
    if not messages:
        return []
    last = messages[-1]
    if last.get("role") != "assistant":
        return []
    content = last.get("content")
    if not isinstance(content, list):
        return []
    ids: list[str] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            bid = b.get("id")
            if isinstance(bid, str) and bid:
                ids.append(bid)
    return ids


def _repair_orphan_tool_uses(messages: list[dict]) -> tuple[list[dict], int]:
    """Walk through ``messages`` and ensure every assistant ``tool_use`` block
    has a matching ``tool_result`` block in the immediately-following user
    message. Synthesises ``is_error: true`` tool_results for any orphans
    (typically left behind when tool execution was interrupted). Returns
    ``(repaired, inserted_count)``.

    Anthropic rejects the request if any ``tool_use`` is not followed by a
    matching ``tool_result``, so this repair runs both at session load and at
    the start of every ``run()`` to keep an interrupted prior turn from
    poisoning the next request.
    """
    repaired: list[dict] = []
    inserted = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        repaired.append(msg)
        if msg.get("role") != "assistant":
            i += 1
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            i += 1
            continue
        tool_use_ids = [
            b.get("id")
            for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        ]
        if not tool_use_ids:
            i += 1
            continue

        existing_result_ids: set[str] = set()
        next_idx = i + 1
        next_is_user_results = (
            next_idx < len(messages)
            and messages[next_idx].get("role") == "user"
            and isinstance(messages[next_idx].get("content"), list)
        )
        if next_is_user_results:
            for b in messages[next_idx]["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tid = b.get("tool_use_id")
                    if tid:
                        existing_result_ids.add(tid)

        missing = [tid for tid in tool_use_ids if tid not in existing_result_ids]
        if not missing:
            i += 1
            continue

        synthetic = [
            {
                "type": "tool_result",
                "tool_use_id": tid,
                "content": _INTERRUPTED_TOOL_RESULT,
                "is_error": True,
            }
            for tid in missing
        ]
        if next_is_user_results:
            merged_content = list(messages[next_idx]["content"]) + synthetic
            repaired.append({"role": "user", "content": merged_content})
            inserted += len(synthetic)
            i += 2
        else:
            repaired.append({"role": "user", "content": synthetic})
            inserted += len(synthetic)
            i += 1
    return repaired, inserted


class Agent:
    _LINE_PREFIX = "assistant> "
    _LINE_PREFIX_AUTONOMOUS = ""
    _USER_PROMPT = "you> "

    _MAX_TOKENS_RETRIES = MAX_TOKENS_RETRIES

    def __init__(self, config: AgentConfig):
        from micro_x_agent_loop.agent_builder import build_agent_components

        c = build_agent_components(config)

        # --- Core LLM ---
        self._provider = c.provider
        self._model = c.model
        self._max_tokens = c.max_tokens
        self._temperature = c.temperature
        self._system_prompt = c.system_prompt
        self._messages: list[dict] = []
        self._tool_map = c.tool_map
        self._converted_tools = c.converted_tools

        # --- Tool search ---
        self._tool_search_active = c.tool_search_active
        self._tool_search_manager = c.tool_search_manager

        # --- Channel & display ---
        self._autonomous = c.autonomous
        self._channel = c.channel
        self._line_prefix = c.line_prefix

        # --- Sub-agents, tasks & compact prompt ---
        self._sub_agent_runner = c.sub_agent_runner
        self._task_manager = c.task_manager
        self._compact_system_prompt = c.compact_system_prompt

        # --- Tool result & conversation limits ---
        self._max_tool_result_chars = c.max_tool_result_chars
        self._max_conversation_messages = c.max_conversation_messages
        self._max_agentic_iterations = c.max_agentic_iterations
        self._compaction_strategy = c.compaction_strategy
        self._memory_enabled = c.memory_enabled

        # --- Memory ---
        self._memory: ActiveMemoryFacade | NullMemoryFacade = c.memory

        # --- Message state ---
        self._current_user_message_id: str | None = None
        self._current_user_message_text: str | None = None
        self._current_checkpoint_id: str | None = None
        self._last_assistant_message_id: str | None = None
        self._run_lock = asyncio.Lock()

        # --- User memory ---
        self._user_memory_enabled = c.user_memory_enabled
        self._user_memory_dir = c.user_memory_dir

        # --- Metrics ---
        self._metrics_enabled = c.metrics_enabled
        self._turn_number = 0
        self._session_config_emitted = False
        self._session_accumulator = c.session_accumulator
        self._session_budget_usd = c.session_budget_usd
        self._budget_warning_emitted = False

        # Wire compaction callback (needs self)
        if self._metrics_enabled and isinstance(self._compaction_strategy, SummarizeCompactionStrategy):
            self._compaction_strategy._on_compaction_completed = self._on_compaction_completed

        # --- Voice runtime (needs self for callback) ---
        if c.autonomous:
            self._voice_runtime = None
        else:
            self._voice_runtime = VoiceRuntime(
                line_prefix=self._line_prefix,
                tool_map=self._tool_map,
                on_utterance=self._process_voice_utterance,
            )

        # --- Services ---
        self._session_controller = SessionController(line_prefix=self._line_prefix)
        self._checkpoint_service = CheckpointService(line_prefix=self._line_prefix)

        # --- Mode analysis ---
        self._mode_analysis_enabled = c.mode_analysis_enabled
        self._stage2_classification_enabled = c.stage2_classification_enabled
        self._stage2_model = c.stage2_model
        self._stage2_provider = c.stage2_provider
        self._working_directory = c.working_directory

        # --- Tool result formatting ---
        self._tool_result_formatter = c.tool_result_formatter
        self._api_payload_store = c.api_payload_store

        # --- Routing state ---
        self._semantic_routing_enabled = c.semantic_routing_enabled
        self._routing_feedback_store = c.routing_feedback_store
        self._task_embedding_index = c.task_embedding_index

        # --- Observability seam (ADR-026) ---
        # Single emit path: facts are persisted once to the event log (source of
        # truth) and fanned out to projection sinks. metrics.jsonl and
        # routing_outcomes are projections here, not independent writers.
        self._obs = ObservabilityEmitter(self._memory)
        self._obs.subscribe(metrics_jsonl_subscriber)
        if self._routing_feedback_store is not None:
            self._obs.subscribe(make_routing_outcome_subscriber(self._routing_feedback_store))
        # Optional external observability exporters (OTel, alerting) attached
        # post-construction by bootstrap; their closers run on shutdown.
        self._observability_closers: list[Callable[[], None]] = []

        # Wire routing feedback callback (captures self). It no longer writes the
        # routing DB directly — it emits a routing.decision event onto the seam,
        # and the routing-outcomes projection persists it.
        routing_feedback_callback = c.routing_feedback_callback
        if c.routing_feedback_store is not None and c.semantic_routing_enabled:

            def _on_routing_feedback(
                *, task_classification: object, usage: UsageResult, call_type: str, decision: object = None
            ) -> None:
                from micro_x_agent_loop.semantic_classifier import TaskClassification as TC

                if not isinstance(task_classification, TC):
                    return
                payload: dict = {
                    "session_id": self._memory.active_session_id or "",
                    "turn_number": self._turn_number,
                    "task_type": task_classification.task_type.value,
                    "provider": usage.provider,
                    "model": usage.model,
                    "cost_usd": estimate_cost(usage),
                    "latency_ms": usage.duration_ms,
                    "stage": task_classification.stage,
                    "confidence": task_classification.confidence,
                    "reason": task_classification.reason,
                    "call_type": call_type,
                }
                if isinstance(decision, RoutingDecision):
                    payload.update(
                        {
                            "policy_name": decision.policy_name,
                            "tool_search_only": decision.tool_search_only,
                            "system_prompt_compact": decision.system_prompt_compact,
                            "pin_continuation_latched": decision.pin_continuation_latched,
                            "confidence_gate_triggered": decision.confidence_gate_triggered,
                        }
                    )
                self._obs.emit("routing.decision", payload, turn_number=self._turn_number)

            routing_feedback_callback = _on_routing_feedback

        # --- TurnEngine ---
        self._turn_engine = TurnEngine(
            provider=self._provider,
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system_prompt=self._system_prompt,
            converted_tools=self._converted_tools,
            tool_map=self._tool_map,
            max_tool_result_chars=self._max_tool_result_chars,
            max_tokens_retries=self._MAX_TOKENS_RETRIES,
            max_agentic_iterations=self._max_agentic_iterations,
            events=self,
            channel=self._channel,
            summarization_provider=c.summarization_provider,
            summarization_model=c.summarization_model,
            summarization_enabled=c.summarization_enabled,
            summarization_threshold=c.summarization_threshold,
            tool_result_overrides=c.tool_result_overrides,
            formatter=self._tool_result_formatter,
            api_payload_store=self._api_payload_store,
            tool_search_manager=self._tool_search_manager,
            tool_search_globally_active=self._tool_search_active,
            compact_system_prompt=self._compact_system_prompt,
            sub_agent_runner=self._sub_agent_runner,
            task_manager=self._task_manager,
            provider_pool=c.provider_pool,
            semantic_classifier=c.semantic_classifier,
            routing_policies=c.routing_policies,
            routing_fallback_provider=c.routing_fallback_provider,
            routing_fallback_model=c.routing_fallback_model,
            routing_feedback_callback=routing_feedback_callback,
            routing_confidence_threshold=c.routing_confidence_threshold,
            task_embedding_index=self._task_embedding_index,
        )

        # --- Commands (need self for callbacks) ---
        commands_dir = Path(self._working_directory or ".") / ".commands"
        self._prompt_command_store = PromptCommandStore(commands_dir)

        self._command_handler = CommandHandler(
            line_prefix=self._line_prefix,
            session_accumulator=self._session_accumulator,
            memory=self._memory,
            memory_enabled=self._memory_enabled,
            tool_map=self._tool_map,
            tool_result_formatter=self._tool_result_formatter,
            api_payload_store=self._api_payload_store,
            voice_runtime=self._voice_runtime,
            session_controller=self._session_controller,
            checkpoint_service=self._checkpoint_service,
            user_memory_enabled=self._user_memory_enabled,
            user_memory_dir=self._user_memory_dir,
            prompt_command_store=self._prompt_command_store,
            on_session_reset=self._on_session_reset,
            on_force_compact=self._on_force_compact,
            on_tools_deleted=self._on_tools_deleted,
            output=self._channel.emit_system_message if self._channel is not None else print,
            routing_feedback_store=self._routing_feedback_store,
        )

        self._command_router = CommandRouter(
            on_help=self._command_handler.on_help,
            on_command=self._command_handler.handle_command,
            on_rewind=self._command_handler.handle_rewind,
            on_checkpoint=self._command_handler.handle_checkpoint,
            on_session=self._command_handler.handle_session,
            on_voice=self._command_handler.handle_voice,
            on_cost=self._command_handler.handle_cost,
            on_replay=self._command_handler.handle_replay,
            on_memory=self._command_handler.handle_memory,
            on_tools=self._command_handler.handle_tools,
            on_tool=self._command_handler.handle_tool,
            on_console_log_level=self._command_handler.handle_console_log_level,
            on_debug=self._command_handler.handle_debug,
            on_routing=self._command_handler.handle_routing,
            on_compact=self._command_handler.handle_compact,
            on_codegen_task_list=self._command_handler.handle_codegen_task_list,
            on_unknown=self._command_handler.on_unknown_command,
        )

    async def initialize_session(self) -> None:
        session_id = self._memory.active_session_id
        if not self._memory_enabled or session_id is None:
            return
        loaded = self._memory.load_messages(session_id)
        repaired, dropped = _repair_orphan_head(loaded)
        if dropped > 0:
            logger.warning(
                f"Session {session_id}: dropped {dropped} leading message(s) with orphan tool_result "
                f"blocks before the head — likely corrupted by an earlier trim bug"
            )
        repaired, inserted = _repair_orphan_tool_uses(repaired)
        if inserted > 0:
            logger.warning(
                f"Session {session_id}: synthesised {inserted} tool_result block(s) for orphan tool_use "
                f"blocks — previous turn(s) likely interrupted before tool execution completed"
            )
        self._messages = repaired
        logger.info(f"Loaded {len(self._messages)} persisted messages for session {session_id}")
        self._inject_task_summary()

    def _inject_task_summary(self) -> None:
        """Append a task-state reminder when resuming a session with existing tasks."""
        if self._task_manager is None:
            return
        summary = self._task_manager.format_task_summary()
        if summary is None:
            return
        self._messages.append(
            {
                "role": "user",
                "content": (
                    "[Session resumed — existing tasks from previous session]\n\n"
                    f"{summary}\n\n"
                    "Review these tasks and continue where you left off. "
                    "Use task_list / task_get to check details before proceeding."
                ),
            }
        )
        logger.info("Injected task summary into resumed session")

    async def run(self, user_message: str) -> None:
        async with self._run_lock:
            self._messages, inserted = _repair_orphan_tool_uses(self._messages)
            if inserted > 0:
                logger.warning(
                    f"Repaired {inserted} orphan tool_use block(s) in-memory before run "
                    f"— previous turn was likely interrupted mid-tool"
                )
            try:
                if self._channel is not None:
                    from micro_x_agent_loop.mcp.mcp_manager import (
                        add_notification_channel,
                        remove_notification_channel,
                    )

                    add_notification_channel(self._channel)
                    try:
                        await self._run_inner(user_message)
                    finally:
                        remove_notification_channel(self._channel)
                else:
                    await self._run_inner(user_message)
            except asyncio.CancelledError:
                self._patch_cancelled_orphans()
                raise

    def _patch_cancelled_orphans(self) -> None:
        """If the run was cancelled mid-tool (typically by ESC in the TUI), the
        last assistant message in ``self._messages`` may contain ``tool_use``
        blocks with no following ``tool_result``. Append a synthetic
        ``tool_result`` (with ``is_error: true``) for each orphan id so both
        in-memory history and the persisted session stay valid for the next
        request. Without this, the next prompt sends an unpaired ``tool_use``
        and Anthropic rejects with HTTP 400.
        """
        orphan_ids = _find_tail_orphan_tool_use_ids(self._messages)
        if not orphan_ids:
            return
        synthetic = [
            {
                "type": "tool_result",
                "tool_use_id": tid,
                "content": _INTERRUPTED_TOOL_RESULT,
                "is_error": True,
            }
            for tid in orphan_ids
        ]
        self.on_append_message("user", synthetic)
        logger.warning(
            f"Run cancelled mid-tool; appended {len(synthetic)} synthetic tool_result block(s) "
            f"for orphan tool_use id(s): {', '.join(orphan_ids)}"
        )

    async def initialize_tool_search_embeddings(self) -> None:
        """Build the embedding index for semantic tool search. Call once at startup."""
        if self._tool_search_manager is not None:
            await self._tool_search_manager.initialize_embeddings()

    async def initialize_task_embeddings(self) -> None:
        """Build the task type embedding index for semantic routing. Call once at startup."""
        if self._task_embedding_index is not None:
            from micro_x_agent_loop.embedding import TaskEmbeddingIndex

            if isinstance(self._task_embedding_index, TaskEmbeddingIndex):
                success = await self._task_embedding_index.build()
                if not success:
                    logger.warning("Task embedding index unavailable — falling back to keywords")

    async def _run_inner(self, user_message: str) -> None:
        # /prompt <filename> — read file and use contents as the user message
        stripped = user_message.strip()
        if stripped.startswith("/prompt "):
            filename = stripped[len("/prompt ") :].strip()
            if not filename:
                self._system_print(f"{self._line_prefix}Usage: /prompt <filename>")
                return
            resolved = self._resolve_file(filename)
            if resolved is None:
                self._system_print(f"{self._line_prefix}File not found: {filename}")
                return
            try:
                user_message = resolved.read_text(encoding="utf-8")
            except OSError as ex:
                self._system_print(f"{self._line_prefix}Error reading file: {ex}")
                return

        command_result = await self._handle_local_command(user_message)
        if command_result is True:
            return
        if isinstance(command_result, str):
            user_message = command_result

        mode_event: dict | None = None
        if self._mode_analysis_enabled and not self._autonomous:
            analysis = analyze_prompt(user_message)
            stage2: Stage2Result | None = None

            if analysis.recommended_mode == RecommendedMode.AMBIGUOUS and self._stage2_classification_enabled:
                try:
                    stage2 = await self._classify_ambiguous(user_message, analysis)
                except Exception as ex:
                    logger.warning(f"Stage 2 classification failed: {ex}")

            user_choice: str | None = None
            if analysis.signals:
                chosen_mode = await self._prompt_mode_choice(analysis, stage2)
                user_choice = chosen_mode.value
                self._system_print(f"[Mode] Proceeding in {chosen_mode.value} mode")
            else:
                self._system_print(format_analysis(analysis))

            mode_event = {
                "session_id": self._memory.active_session_id or "",
                "signals": [
                    {"name": s.name, "strength": s.strength.value, "matched_text": s.matched_text}
                    for s in analysis.signals
                ],
                "stage1_recommendation": analysis.recommended_mode.value,
                "stage2_recommendation": stage2.recommended_mode.value if stage2 is not None else None,
                "stage2_reasoning": stage2.reasoning if stage2 is not None else "",
                "user_choice": user_choice,
            }

        # Budget check — refuse to start a new turn if budget is exhausted
        if self._is_budget_exceeded():
            budget = self._session_budget_usd
            spent = self._session_accumulator.total_cost_usd
            self._system_print(
                f"{self._line_prefix}Session budget exhausted "
                f"(${spent:.4f} / ${budget:.2f}). "
                f"Use /cost for details. Start a new session or increase SessionBudgetUSD."
            )
            return

        self._turn_number += 1
        self._session_accumulator.total_turns = self._turn_number

        self._emit_session_config_once()
        if mode_event is not None:
            self._obs.emit("mode.analyzed", mode_event, turn_number=self._turn_number)

        self._current_checkpoint_id = None
        self._last_assistant_message_id = None
        self._current_user_message_text = user_message

        if self._channel is not None and hasattr(self._channel, "begin_streaming"):
            self._channel.begin_streaming()
        try:
            current_user_message_id, last_assistant_message_id = await self._turn_engine.run(
                messages=self._messages,
                user_message=user_message,
                turn_number=self._turn_number,
            )
        finally:
            if self._channel is not None and hasattr(self._channel, "end_streaming"):
                self._channel.end_streaming()

        self._current_user_message_id = current_user_message_id
        self._last_assistant_message_id = last_assistant_message_id
        self._update_context_stats()

    # -- Mode choice prompt --

    async def _prompt_mode_choice(
        self,
        analysis: ModeAnalysis,
        stage2: Stage2Result | None,
    ) -> RecommendedMode:
        """Prompt the user to choose between PROMPT and COMPILED execution mode."""
        # Determine the recommendation to present
        if stage2:
            recommended = stage2.recommended_mode
        else:
            recommended = analysis.recommended_mode
        # AMBIGUOUS with no stage2 override defaults to COMPILED recommendation
        if recommended == RecommendedMode.AMBIGUOUS:
            recommended = RecommendedMode.COMPILED

        # Build signal descriptions for display
        signal_texts = [f'{s.name} ({s.strength.value}): "{s.matched_text}"' for s in analysis.signals]
        reasoning = stage2.reasoning if stage2 and stage2.reasoning else ""
        recommended_str = recommended.value

        # Route through channel if it supports mode choice (e.g. TUI modal)
        if self._channel is not None and hasattr(self._channel, "prompt_mode_choice"):
            selected = await self._channel.prompt_mode_choice(
                signal_texts,
                recommended_str,
                reasoning,
            )
            if selected == "COMPILED":
                return RecommendedMode.COMPILED
            if selected == "PROMPT":
                return RecommendedMode.PROMPT
            return recommended

        # Fallback: interactive terminal prompt via questionary
        self._system_print(
            "[Mode Analysis] Your prompt contains signals that suggest compiled (batch) mode may be more appropriate:"
        )
        for text in signal_texts:
            self._system_print(f"  * {text}")
        if reasoning:
            self._system_print(f"  LLM assessment: {reasoning}")
        self._system_print(
            "  PROMPT mode: conversational, single-turn responses\n  COMPILED mode: structured batch execution"
        )

        import questionary
        from questionary import Choice, Style

        compiled_label = "COMPILED"
        prompt_label = "PROMPT"
        if recommended == RecommendedMode.COMPILED:
            compiled_label += " (recommended)"
        else:
            prompt_label += " (recommended)"

        choices = [
            Choice(
                title=f"{compiled_label} — structured batch execution",
                value="COMPILED",
            ),
            Choice(
                title=f"{prompt_label} — conversational response",
                value="PROMPT",
            ),
        ]

        style = Style(
            [
                ("qmark", "fg:cyan bold"),
                ("question", "bold"),
                ("pointer", "fg:cyan bold"),
                ("highlighted", "fg:cyan bold"),
                ("selected", "fg:cyan"),
            ]
        )

        def _do_select() -> str | None:
            result: str | None = questionary.select(
                "Which execution mode should be used?",
                choices=choices,
                style=style,
            ).ask()
            return result

        try:
            selected = await asyncio.to_thread(_do_select)
        except Exception:
            self._system_print(f"[Mode Analysis] Non-interactive terminal, using recommendation: {recommended.value}")
            return recommended

        if selected == "COMPILED":
            return RecommendedMode.COMPILED
        if selected == "PROMPT":
            return RecommendedMode.PROMPT
        # User cancelled (Ctrl-C) — use recommendation
        return recommended

    # -- Stage 2 LLM classification --

    async def _classify_ambiguous(self, user_message: str, stage1: ModeAnalysis) -> Stage2Result:
        """Call the LLM to classify an ambiguous prompt as PROMPT or COMPILED."""
        prompt = build_stage2_prompt(user_message, stage1)
        assert self._stage2_provider is not None
        response_text, usage = await self._stage2_provider.create_message(
            self._stage2_model, 300, 0.0, [{"role": "user", "content": prompt}]
        )
        self.on_api_call_completed(usage, call_type="stage2_classification")
        return parse_stage2_response(response_text)

    # -- TurnEvents protocol: metrics --

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None:
        # Feed actual token count to smart compaction trigger
        if call_type == "main" and isinstance(self._compaction_strategy, SummarizeCompactionStrategy):
            self._compaction_strategy.update_actual_tokens(usage.input_tokens)

        if not self._metrics_enabled:
            return
        self._session_accumulator.add_api_call(usage, call_type=call_type, turn_number=self._turn_number)

        # Budget warning at threshold (once per session)
        self._check_budget_warning()
        metric = build_api_call_metric(
            usage,
            session_id=self._memory.active_session_id or "",
            turn_number=self._turn_number,
            call_type=call_type,
        )
        self._obs.emit("metric.api_call", metric, turn_number=self._turn_number)

    def on_api_call_failed(
        self, *, model: str, provider: str, call_type: str, error: BaseException
    ) -> None:
        # A terminal LLM call failure (provider retry already exhausted). The
        # success metric never fires on error, so record it here — otherwise a
        # 429 / timeout leaves no structured trace. Always log a warning for
        # visibility in agent.log; emit the structured metric when enabled.
        logger.warning(
            "API call failed: provider={provider} model={model} call_type={call_type} error={err}",
            provider=provider or "?",
            model=model or "?",
            call_type=call_type,
            err=f"{type(error).__name__}: {error}"[:300],
        )
        if not self._metrics_enabled:
            return
        metric = build_api_call_error_metric(
            model=model,
            provider=provider,
            session_id=self._memory.active_session_id or "",
            turn_number=self._turn_number,
            call_type=call_type,
            error=error,
        )
        self._obs.emit("metric.api_call_error", metric, turn_number=self._turn_number)

    def on_turn_cap_reached(self, iterations: int) -> None:
        # Behavioural signal (set regardless of metrics_enabled): the turn
        # stopped because it hit MaxAgenticIterations, not because the model
        # finished. Surfaced via SessionAccumulator so evals can assert on it.
        self._session_accumulator.turn_cap_reached = True
        logger.warning(
            "Agentic turn cap reached: {n} iterations (MaxAgenticIterations)",
            n=iterations,
        )

    def on_tool_executed(
        self,
        tool_name: str,
        result_chars: int,
        duration_ms: float,
        is_error: bool,
        *,
        was_summarized: bool = False,
    ) -> None:
        if not self._metrics_enabled:
            return
        self._session_accumulator.add_tool_call(tool_name, is_error)
        metric = build_tool_execution_metric(
            tool_name=tool_name,
            result_chars=result_chars,
            duration_ms=duration_ms,
            is_error=is_error,
            session_id=self._memory.active_session_id or "",
            turn_number=self._turn_number,
            was_summarized=was_summarized,
        )
        self._obs.emit("metric.tool_execution", metric, turn_number=self._turn_number)

    def _on_compaction_completed(
        self, usage: UsageResult, tokens_before: int, tokens_after: int, messages_compacted: int
    ) -> None:
        self._session_accumulator.add_compaction(usage)
        metric = build_compaction_metric(
            usage=usage,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_compacted=messages_compacted,
            session_id=self._memory.active_session_id or "",
            turn_number=self._turn_number,
        )
        self._obs.emit("metric.compaction", metric, turn_number=self._turn_number)

    # -- TurnEvents protocol: core callbacks --

    async def on_maybe_compact(self) -> None:
        self._messages = await self._compaction_strategy.maybe_compact(self._messages)
        self._trim_conversation_history()

    async def _on_force_compact(self, protected_tail: int | None = None) -> tuple[bool, str]:
        """Force compaction regardless of token threshold. Returns (ok, message)."""
        if not isinstance(self._compaction_strategy, SummarizeCompactionStrategy):
            return False, "Compaction not available (strategy is 'none')."
        if len(self._messages) < 3:
            return False, "Not enough messages to compact."

        from micro_x_agent_loop.compaction import estimate_tokens

        tokens_before = estimate_tokens(self._messages)
        # Temporarily override threshold and optionally protected tail
        saved_threshold = self._compaction_strategy._threshold_tokens
        saved_tail = self._compaction_strategy._protected_tail_messages
        self._compaction_strategy._threshold_tokens = 0
        if protected_tail is not None:
            self._compaction_strategy._protected_tail_messages = protected_tail
        try:
            self._messages = await self._compaction_strategy.maybe_compact(self._messages)
        finally:
            self._compaction_strategy._threshold_tokens = saved_threshold
            self._compaction_strategy._protected_tail_messages = saved_tail
        self._trim_conversation_history()
        self._update_context_stats()
        tokens_after = estimate_tokens(self._messages)
        return True, (
            f"Compacted: ~{tokens_before:,} → ~{tokens_after:,} tokens ({len(self._messages)} messages remaining)."
        )

    def _update_context_stats(self) -> None:
        from micro_x_agent_loop.compaction import estimate_tokens

        self._session_accumulator.context_tokens = estimate_tokens(self._messages)
        self._session_accumulator.context_messages = len(self._messages)

    def _trim_conversation_history(self) -> None:
        safe = _find_safe_trim_count(self._messages, self._max_conversation_messages)
        if safe == 0:
            target = max(0, len(self._messages) - self._max_conversation_messages)
            if target > 0:
                logger.info(
                    f"Conversation history trim skipped — no safe boundary found "
                    f"(target={target}, len={len(self._messages)})"
                )
            return
        target = len(self._messages) - self._max_conversation_messages
        if safe != target:
            logger.info(
                f"Conversation history trim adjusted {target} -> {safe} to avoid orphaning tool_result"
            )
        logger.info(
            f"Conversation history trimmed - removed {safe} oldest message(s) "
            f"to stay within the {self._max_conversation_messages} message limit"
        )
        del self._messages[:safe]

    def on_append_message(self, role: str, content: str | list[dict]) -> str | None:
        self._messages.append({"role": role, "content": content})
        return self._memory.append_message(role, content)

    def on_ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None:
        self._current_checkpoint_id = self._memory.ensure_checkpoint_for_turn(
            tool_use_blocks,
            user_message_id=self._current_user_message_id,
            user_message_text=self._current_user_message_text,
            current_checkpoint_id=self._current_checkpoint_id,
        )

    def on_maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None:
        self._memory.maybe_track_mutation(tool_name, tool, tool_input, self._current_checkpoint_id)

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        self._memory.emit_tool_started(tool_use_id, tool_name)

    def on_user_message_appended(self, message_id: str | None) -> None:
        self._current_user_message_id = message_id

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        self._memory.emit_tool_completed(tool_use_id, tool_name, is_error)

    def on_subagent_completed(
        self,
        *,
        agent_type: str,
        task: str,
        result_summary: str,
        turns: int,
        timed_out: bool,
        cost_usd: float,
        api_calls: int,
    ) -> None:
        self._memory.emit_event(
            "subagent.completed",
            {
                "agent_type": agent_type,
                "task": task[:500],
                "result_summary": result_summary[:500],
                "turns": turns,
                "timed_out": timed_out,
                "cost_usd": cost_usd,
                "api_calls": api_calls,
            },
        )

    def on_record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
        was_truncated: bool = False,
        original_chars: int | None = None,
    ) -> None:
        self._memory.record_tool_call(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
            result_text=result_text,
            is_error=is_error,
            message_id=message_id,
            was_truncated=was_truncated,
            original_chars=original_chars,
        )

    def on_llm_call(
        self,
        *,
        turn_iteration: int,
        call_type: str,
        effective_provider: str,
        effective_model: str,
        temperature: float,
        max_tokens: int,
        message_count: int,
        tool_names: list[str],
        system_prompt: str,
        routing_rule: str = "",
        routing_reason: str = "",
    ) -> None:
        # Step-through trace of the exact LLM input. The full prompt is deduped
        # into the system_prompts table; the event carries only its hash + size.
        sha = self._memory.persist_system_prompt(system_prompt)
        self._obs.emit(
            "llm.call",
            {
                "session_id": self._memory.active_session_id or "",
                "turn_number": self._turn_number,
                "call_type": call_type,
                "effective_provider": effective_provider,
                "effective_model": effective_model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "message_count": message_count,
                "tool_names": tool_names,
                "system_prompt_sha256": sha,
                "system_prompt_chars": len(system_prompt),
                "routing_rule": routing_rule,
                "routing_reason": routing_reason,
            },
            turn_number=self._turn_number,
            iteration=turn_iteration,
        )

    def add_observability_subscriber(
        self, callback: Callable[[str, dict], None], *, closer: Callable[[], None] | None = None
    ) -> None:
        """Attach an external observability sink (OTel, alerting) to the emit seam.

        Called by bootstrap after construction so exporters needn't thread
        through AgentConfig. ``closer`` (if given) runs on ``shutdown``.
        """
        self._obs.subscribe(callback)
        if closer is not None:
            self._observability_closers.append(closer)

    def _emit_session_config_once(self) -> None:
        """Emit a ``session.config`` event once per session.

        Snapshots the resolved scalar config that drives agent decisions, plus a
        ``code_sha`` and a ``config_hash`` so a historical trace can be
        interpreted against the exact code + config that produced it (ADR
        review gap: historical traces vs today's code).
        """
        if self._session_config_emitted:
            return
        self._session_config_emitted = True
        snapshot = {
            "model": self._model,
            "provider": getattr(self._provider, "family", ""),
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "max_agentic_iterations": self._max_agentic_iterations,
            "semantic_routing_enabled": self._semantic_routing_enabled,
            "mode_analysis_enabled": self._mode_analysis_enabled,
            "stage2_classification_enabled": self._stage2_classification_enabled,
            "memory_enabled": self._memory_enabled,
            "metrics_enabled": self._metrics_enabled,
            "session_budget_usd": self._session_budget_usd,
            "system_prompt_chars": len(self._system_prompt),
        }
        self._obs.emit(
            "session.config",
            {
                "session_id": self._memory.active_session_id or "",
                "code_sha": resolve_code_sha(),
                "config_hash": config_hash(snapshot),
                "config": snapshot,
            },
            turn_number=self._turn_number,
        )

    def _system_print(self, text: str) -> None:
        """Print system output through the channel if available, else stdout."""
        if self._channel is not None:
            self._channel.emit_system_message(text)
        else:
            print(text)

    async def _handle_local_command(self, user_message: str) -> bool | str:
        return await self._command_router.try_handle(user_message)

    def _on_session_reset(self, session_id: str, new_messages: list[dict]) -> None:
        self._messages = new_messages
        self._session_accumulator.reset(session_id=session_id)
        self._turn_number = 0
        self._session_config_emitted = False
        self._budget_warning_emitted = False
        if self._task_manager is not None:
            self._task_manager._list_id = session_id
        self._inject_task_summary()

    def _on_tools_deleted(self, tool_names: list[str]) -> None:
        if not tool_names:
            return
        to_remove = set(tool_names)
        self._converted_tools[:] = [tool for tool in self._converted_tools if tool.get("name") not in to_remove]
        if self._tool_search_manager is not None:
            self._tool_search_manager.remove_tools(tool_names)

    async def _process_voice_utterance(self, text: str) -> None:
        await self.run(text)
        print(f"\n{self._USER_PROMPT}", end="", flush=True)

    def _resolve_file(self, filename: str) -> Path | None:
        """Resolve a filename to a Path, checking working directory then CWD."""
        path = Path(filename)
        if path.is_absolute():
            return path if path.is_file() else None
        if self._working_directory:
            candidate = Path(self._working_directory) / path
            if candidate.is_file():
                return candidate
        candidate = Path.cwd() / path
        if candidate.is_file():
            return candidate
        return None

    async def shutdown(self) -> None:
        if self._metrics_enabled:
            summary = build_session_summary_metric(self._session_accumulator)
            self._obs.emit("metric.session_summary", summary, turn_number=self._turn_number)
        if self._routing_feedback_store is not None:
            self._routing_feedback_store.close()
        for closer in self._observability_closers:
            try:
                closer()
            except Exception as ex:
                logger.warning(f"Observability closer failed: {ex}")
        if self._voice_runtime:
            await self._voice_runtime.shutdown()

    @property
    def active_session_id(self) -> str | None:
        return self._memory.active_session_id

    @property
    def session_accumulator(self) -> SessionAccumulator:
        return self._session_accumulator

    # -- Budget helpers --

    def _is_budget_exceeded(self) -> bool:
        """Return True if a session budget is set and spending has reached or exceeded it."""
        if self._session_budget_usd <= 0:
            return False
        return self._session_accumulator.total_cost_usd >= self._session_budget_usd

    def _check_budget_warning(self) -> None:
        """Emit a one-time warning when spending crosses the warn threshold."""
        if self._session_budget_usd <= 0 or self._budget_warning_emitted:
            return
        spent = self._session_accumulator.total_cost_usd
        warn_at = self._session_budget_usd * SESSION_BUDGET_WARN_THRESHOLD
        if spent >= warn_at:
            self._budget_warning_emitted = True
            pct = spent / self._session_budget_usd * 100
            self._system_print(
                f"{self._line_prefix}[Budget] {pct:.0f}% of session budget used "
                f"(${spent:.4f} / ${self._session_budget_usd:.2f})"
            )

    # Backward-compatible wrappers for existing tests.
    async def _handle_session_command(self, command: str) -> None:
        await self._command_handler.handle_session(command)

    async def _handle_rewind_command(self, command: str) -> None:
        await self._command_handler.handle_rewind(command)

    async def _handle_checkpoint_command(self, command: str) -> None:
        await self._command_handler.handle_checkpoint(command)

    async def _handle_cost_command(self, command: str) -> None:
        await self._command_handler.handle_cost(command)

    async def _execute_tools(self, tool_use_blocks: list[dict]) -> list[dict]:
        return await self._turn_engine.execute_tools(
            tool_use_blocks,
            last_assistant_message_id=self._last_assistant_message_id,
        )

    def _short_id(self, value: str, length: int = 8) -> str:
        _ = length
        return self._session_controller.short_id(value)

    def _format_session_list_entry(self, session: dict) -> str:
        return self._session_controller.format_session_list_entry(
            session, active_session_id=self._memory.active_session_id
        )

    def _format_checkpoint_list_entry(self, checkpoint: dict) -> str:
        return self._checkpoint_service.format_checkpoint_list_entry(checkpoint)

    def _print_resumed_session_summary(self, summary: dict) -> None:
        for line in self._session_controller.format_resumed_summary_lines(summary):
            print(line)
