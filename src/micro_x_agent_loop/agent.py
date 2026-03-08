from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.commands.command_handler import CommandHandler
from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore
from micro_x_agent_loop.commands.router import CommandRouter
from micro_x_agent_loop.compaction import SummarizeCompactionStrategy
from micro_x_agent_loop.constants import MAX_TOKENS_RETRIES
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import (
    SessionAccumulator,
    build_api_call_metric,
    build_compaction_metric,
    build_session_summary_metric,
    build_tool_execution_metric,
    emit_metric,
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
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.tool_search import ToolSearchManager, should_activate_tool_search
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult
from micro_x_agent_loop.voice_runtime import VoiceRuntime


class Agent:
    _LINE_PREFIX = "assistant> "
    _LINE_PREFIX_AUTONOMOUS = ""
    _USER_PROMPT = "you> "

    _MAX_TOKENS_RETRIES = MAX_TOKENS_RETRIES

    def __init__(self, config: AgentConfig):
        self._provider = create_provider(
            config.provider, config.api_key,
            prompt_caching_enabled=config.prompt_caching_enabled,
        )
        self._model = config.model
        self._max_tokens = config.max_tokens
        self._temperature = config.temperature
        self._system_prompt = config.system_prompt
        self._messages: list[dict] = []
        self._tool_map: dict[str, Tool] = {t.name: t for t in config.tools}
        self._converted_tools = self._provider.convert_tools(config.tools)

        # Tool search (on-demand tool discovery)
        self._tool_search_active = should_activate_tool_search(
            config.tool_search_enabled,
            self._converted_tools,
            config.model,
        )
        self._tool_search_manager: ToolSearchManager | None = None
        if self._tool_search_active:
            self._tool_search_manager = ToolSearchManager(
                all_tools=config.tools,
                converted_tools=self._converted_tools,
            )
            from micro_x_agent_loop.system_prompt import _TOOL_SEARCH_DIRECTIVE
            self._system_prompt += _TOOL_SEARCH_DIRECTIVE
            logger.info(
                f"Tool search active: {len(config.tools)} tools deferred, "
                "LLM will discover tools via tool_search"
            )

        self._autonomous = config.autonomous
        self._channel = config.channel
        self._line_prefix = self._LINE_PREFIX_AUTONOMOUS if config.autonomous else self._LINE_PREFIX

        # Enable ask_user directive when a channel is available
        if self._channel is not None:
            from micro_x_agent_loop.system_prompt import _ASK_USER_DIRECTIVE
            self._system_prompt += _ASK_USER_DIRECTIVE

        self._max_tool_result_chars = config.max_tool_result_chars
        self._max_conversation_messages = config.max_conversation_messages
        self._compaction_strategy = config.compaction_strategy
        self._memory_enabled = config.memory_enabled

        # Memory facade
        if config.memory_enabled and config.session_manager is not None:
            self._memory: ActiveMemoryFacade | NullMemoryFacade = ActiveMemoryFacade(
                session_manager=config.session_manager,
                checkpoint_manager=config.checkpoint_manager,
                event_emitter=config.event_emitter,
                active_session_id=config.session_id,
            )
        else:
            self._memory = NullMemoryFacade()
            self._memory.active_session_id = config.session_id

        self._current_user_message_id: str | None = None
        self._current_user_message_text: str | None = None
        self._current_checkpoint_id: str | None = None
        self._last_assistant_message_id: str | None = None
        self._run_lock = asyncio.Lock()

        # User memory
        self._user_memory_enabled = config.user_memory_enabled
        self._user_memory_dir = config.user_memory_dir

        # Metrics
        self._metrics_enabled = config.metrics_enabled
        self._turn_number = 0
        self._session_accumulator = SessionAccumulator(
            session_id=config.session_id or "",
        )

        # Wire compaction callback if metrics enabled
        if self._metrics_enabled and isinstance(self._compaction_strategy, SummarizeCompactionStrategy):
            self._compaction_strategy._on_compaction_completed = self._on_compaction_completed

        if config.autonomous:
            self._voice_runtime = None
        else:
            self._voice_runtime = VoiceRuntime(
                line_prefix=self._line_prefix,
                tool_map=self._tool_map,
                on_utterance=self._process_voice_utterance,
            )

        self._session_controller = SessionController(line_prefix=self._line_prefix)
        self._checkpoint_service = CheckpointService(line_prefix=self._line_prefix)

        # Mode analysis
        self._mode_analysis_enabled = config.mode_analysis_enabled
        self._stage2_classification_enabled = config.stage2_classification_enabled
        self._stage2_model = config.stage2_model or config.model
        self._working_directory = config.working_directory

        # Tool result summarization
        summarization_provider = None
        summarization_model = ""
        if config.tool_result_summarization_enabled:
            summarization_model = config.tool_result_summarization_model or config.model
            summarization_provider = create_provider(config.provider, config.api_key)

        self._tool_result_formatter = ToolResultFormatter(
            tool_formatting=config.tool_formatting,
            default_format=config.default_format,
        )

        self._api_payload_store = ApiPayloadStore()

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
            events=self,
            channel=self._channel,
            summarization_provider=summarization_provider,
            summarization_model=summarization_model,
            summarization_enabled=config.tool_result_summarization_enabled,
            summarization_threshold=config.tool_result_summarization_threshold,
            formatter=self._tool_result_formatter,
            api_payload_store=self._api_payload_store,
            tool_search_manager=self._tool_search_manager,
        )

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
        )

        self._command_router = CommandRouter(
            on_help=self._command_handler.on_help,
            on_command=self._command_handler.handle_command,
            on_rewind=self._command_handler.handle_rewind,
            on_checkpoint=self._command_handler.handle_checkpoint,
            on_session=self._command_handler.handle_session,
            on_voice=self._command_handler.handle_voice,
            on_cost=self._command_handler.handle_cost,
            on_memory=self._command_handler.handle_memory,
            on_tools=self._command_handler.handle_tools,
            on_tool=self._command_handler.handle_tool,
            on_console_log_level=self._command_handler.handle_console_log_level,
            on_debug=self._command_handler.handle_debug,
            on_unknown=self._command_handler.on_unknown_command,
        )

    async def initialize_session(self) -> None:
        session_id = self._memory.active_session_id
        if not self._memory_enabled or session_id is None:
            return
        self._messages = self._memory.load_messages(session_id)
        logger.info(
            f"Loaded {len(self._messages)} persisted messages for session {session_id}"
        )

    async def run(self, user_message: str) -> None:
        async with self._run_lock:
            await self._run_inner(user_message)

    async def _run_inner(self, user_message: str) -> None:
        # /prompt <filename> — read file and use contents as the user message
        stripped = user_message.strip()
        if stripped.startswith("/prompt "):
            filename = stripped[len("/prompt "):].strip()
            if not filename:
                print(f"{self._line_prefix}Usage: /prompt <filename>")
                return
            resolved = self._resolve_file(filename)
            if resolved is None:
                print(f"{self._line_prefix}File not found: {filename}")
                return
            try:
                user_message = resolved.read_text(encoding="utf-8")
            except OSError as ex:
                print(f"{self._line_prefix}Error reading file: {ex}")
                return

        command_result = await self._handle_local_command(user_message)
        if command_result is True:
            return
        if isinstance(command_result, str):
            user_message = command_result

        if self._mode_analysis_enabled and not self._autonomous:
            analysis = analyze_prompt(user_message)
            stage2: Stage2Result | None = None

            if (analysis.recommended_mode == RecommendedMode.AMBIGUOUS
                    and self._stage2_classification_enabled):
                try:
                    stage2 = await self._classify_ambiguous(user_message, analysis)
                except Exception as ex:
                    logger.warning(f"Stage 2 classification failed: {ex}")

            if analysis.signals:
                # Signals detected — ask the user which mode to use
                chosen_mode = await self._prompt_mode_choice(analysis, stage2)
                print(f"[Mode] Proceeding in {chosen_mode.value} mode")
            else:
                print(format_analysis(analysis))

        self._turn_number += 1
        self._session_accumulator.total_turns = self._turn_number

        self._current_checkpoint_id = None
        self._last_assistant_message_id = None
        self._current_user_message_text = user_message
        current_user_message_id, last_assistant_message_id = await self._turn_engine.run(
            messages=self._messages,
            user_message=user_message,
        )
        self._current_user_message_id = current_user_message_id
        self._last_assistant_message_id = last_assistant_message_id

    # -- Mode choice prompt --

    async def _prompt_mode_choice(
        self, analysis: ModeAnalysis, stage2: Stage2Result | None,
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

        # Print why we're asking
        print("\n[Mode Analysis] Your prompt contains signals that suggest "
              "compiled (batch) mode may be more appropriate:")
        for signal in analysis.signals:
            print(f"  • {signal.name} ({signal.strength.value}): "
                  f'"{signal.matched_text}"')
        if stage2 and stage2.reasoning:
            print(f"  LLM assessment: {stage2.reasoning}")
        print()
        print("  PROMPT mode: conversational, single-turn responses — good for "
              "questions, explanations, and single-item tasks.")
        print("  COMPILED mode: structured batch execution — good for multi-item "
              "processing, data collection, scoring, and repeatable workflows.")
        print()

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

        style = Style([
            ("qmark", "fg:cyan bold"),
            ("question", "bold"),
            ("pointer", "fg:cyan bold"),
            ("highlighted", "fg:cyan bold"),
            ("selected", "fg:cyan"),
        ])

        def _do_select() -> str | None:
            return questionary.select(
                "Which execution mode should be used?",
                choices=choices,
                style=style,
            ).ask()

        try:
            selected = await asyncio.to_thread(_do_select)
        except Exception:
            print(f"[Mode Analysis] Non-interactive terminal, using recommendation: "
                  f"{recommended.value}")
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
        response_text, usage = await self._provider.create_message(
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
        metric = build_api_call_metric(
            usage,
            session_id=self._memory.active_session_id or "",
            turn_number=self._turn_number,
            call_type=call_type,
        )
        emit_metric(metric)

    def on_tool_executed(
        self, tool_name: str, result_chars: int, duration_ms: float, is_error: bool,
        *, was_summarized: bool = False,
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
        emit_metric(metric)

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
        emit_metric(metric)

    # -- TurnEvents protocol: core callbacks --

    async def on_maybe_compact(self) -> None:
        self._messages = await self._compaction_strategy.maybe_compact(self._messages)
        self._trim_conversation_history()

    def _trim_conversation_history(self) -> None:
        if self._max_conversation_messages <= 0:
            return
        if len(self._messages) <= self._max_conversation_messages:
            return

        remove_count = len(self._messages) - self._max_conversation_messages
        if remove_count > 0:
            logger.info(
                f"Conversation history trimmed - removed {remove_count} oldest message(s) "
                f"to stay within the {self._max_conversation_messages} message limit"
            )
            del self._messages[:remove_count]

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

    def on_record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
    ) -> None:
        self._memory.record_tool_call(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
            result_text=result_text,
            is_error=is_error,
            message_id=message_id,
        )

    async def _handle_local_command(self, user_message: str) -> bool | str:
        return await self._command_router.try_handle(user_message)

    def _on_session_reset(self, session_id: str, new_messages: list[dict]) -> None:
        self._messages = new_messages
        self._session_accumulator.reset(session_id=session_id)
        self._turn_number = 0

    async def _process_voice_utterance(self, text: str) -> None:
        await self.run(text)
        print(f"\n{self._USER_PROMPT}", end="", flush=True)

    def _resolve_file(self, filename: str) -> Path | None:
        """Resolve a filename to a Path, checking CWD then working directory."""
        path = Path(filename)
        if path.is_absolute():
            return path if path.is_file() else None
        candidate = Path.cwd() / path
        if candidate.is_file():
            return candidate
        if self._working_directory:
            candidate = Path(self._working_directory) / path
            if candidate.is_file():
                return candidate
        return None

    async def shutdown(self) -> None:
        if self._metrics_enabled:
            emit_metric(build_session_summary_metric(self._session_accumulator))
        if self._voice_runtime:
            await self._voice_runtime.shutdown()

    @property
    def active_session_id(self) -> str | None:
        return self._memory.active_session_id

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
