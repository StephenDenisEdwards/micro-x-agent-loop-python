from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.mode_selector import (
    ModeAnalysis,
    RecommendedMode,
    Stage2Result,
    analyze_prompt,
    build_stage2_prompt,
    format_analysis,
    format_stage2_result,
    parse_stage2_response,
)
from micro_x_agent_loop.commands.router import CommandRouter
from micro_x_agent_loop.commands.voice_command import parse_voice_command, parse_voice_start_options
from micro_x_agent_loop.compaction import SummarizeCompactionStrategy
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import (
    SessionAccumulator,
    build_api_call_metric,
    build_compaction_metric,
    build_session_summary_metric,
    build_tool_execution_metric,
    emit_metric,
)
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult
from micro_x_agent_loop.voice_runtime import VoiceRuntime


class Agent:
    _LINE_PREFIX = "assistant> "
    _USER_PROMPT = "you> "

    _MAX_TOKENS_RETRIES = 3

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

        self._voice_runtime = VoiceRuntime(
            line_prefix=self._LINE_PREFIX,
            tool_map=self._tool_map,
            on_utterance=self._process_voice_utterance,
        )

        self._session_controller = SessionController(line_prefix=self._LINE_PREFIX)
        self._checkpoint_service = CheckpointService(line_prefix=self._LINE_PREFIX)

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
            line_prefix=self._LINE_PREFIX,
            max_tool_result_chars=self._max_tool_result_chars,
            max_tokens_retries=self._MAX_TOKENS_RETRIES,
            events=self,
            summarization_provider=summarization_provider,
            summarization_model=summarization_model,
            summarization_enabled=config.tool_result_summarization_enabled,
            summarization_threshold=config.tool_result_summarization_threshold,
            formatter=self._tool_result_formatter,
            api_payload_store=self._api_payload_store,
        )

        self._command_router = CommandRouter(
            on_help=self._on_help,
            on_rewind=self._handle_rewind_command,
            on_checkpoint=self._handle_checkpoint_command,
            on_session=self._handle_session_command,
            on_voice=self._handle_voice_command,
            on_cost=self._handle_cost_command,
            on_memory=self._handle_memory_command,
            on_tool=self._handle_tool_command,
            on_debug=self._handle_debug_command,
            on_unknown=self._on_unknown_command,
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
                print(f"{self._LINE_PREFIX}Usage: /prompt <filename>")
                return
            resolved = self._resolve_file(filename)
            if resolved is None:
                print(f"{self._LINE_PREFIX}File not found: {filename}")
                return
            try:
                user_message = resolved.read_text(encoding="utf-8")
            except OSError as ex:
                print(f"{self._LINE_PREFIX}Error reading file: {ex}")
                return

        if await self._handle_local_command(user_message):
            return

        if self._mode_analysis_enabled:
            analysis = analyze_prompt(user_message)
            formatted = format_analysis(analysis)
            if formatted:
                print(formatted)

            if (analysis.recommended_mode == RecommendedMode.AMBIGUOUS
                    and self._stage2_classification_enabled):
                try:
                    stage2 = await self._classify_ambiguous(user_message, analysis)
                    print(format_stage2_result(stage2))
                except Exception as ex:
                    logger.warning(f"Stage 2 classification failed: {ex}")
                    print(f"[Mode Analysis] Stage 2 classification failed: {ex}")

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

    # -- /cost command --

    async def _handle_cost_command(self, command: str) -> None:
        print(f"{self._LINE_PREFIX}{self._session_accumulator.format_summary()}")

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

    async def _handle_local_command(self, user_message: str) -> bool:
        return await self._command_router.try_handle(user_message)

    async def _on_help(self) -> None:
        self._print_help()

    def _on_unknown_command(self, trimmed: str) -> None:
        print(f"{self._LINE_PREFIX}Unknown local command: {trimmed}")

    def _print_help(self) -> None:
        print(f"{self._LINE_PREFIX}Available commands:")
        print(f"{self._LINE_PREFIX}- /help")
        print(f"{self._LINE_PREFIX}- /prompt <filename>")
        print(f"{self._LINE_PREFIX}- /cost")
        print(
            f"{self._LINE_PREFIX}- /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>]"
        )
        print(f"{self._LINE_PREFIX}- /voice status")
        print(f"{self._LINE_PREFIX}- /voice devices")
        print(f"{self._LINE_PREFIX}- /voice events [limit]")
        print(f"{self._LINE_PREFIX}- /voice stop")
        print(f"{self._LINE_PREFIX}- /tool")
        print(f"{self._LINE_PREFIX}- /tool <name>")
        print(f"{self._LINE_PREFIX}- /tool <name> schema")
        print(f"{self._LINE_PREFIX}- /tool <name> config")
        print(f"{self._LINE_PREFIX}- /debug show-api-payload [N]")
        if self._user_memory_enabled:
            print(f"{self._LINE_PREFIX}- /memory")
            print(f"{self._LINE_PREFIX}- /memory list")
            print(f"{self._LINE_PREFIX}- /memory edit")
            print(f"{self._LINE_PREFIX}- /memory reset")
        if self._memory_enabled:
            print(f"{self._LINE_PREFIX}- /session")
            print(f"{self._LINE_PREFIX}- /session new [title]")
            print(f"{self._LINE_PREFIX}- /session list [limit]")
            print(f"{self._LINE_PREFIX}- /session name <title>")
            print(f"{self._LINE_PREFIX}- /session resume <id-or-name>")
            print(f"{self._LINE_PREFIX}- /session fork")
            print(f"{self._LINE_PREFIX}- /rewind <checkpoint_id>")
            print(f"{self._LINE_PREFIX}- /checkpoint list [limit]")
            print(f"{self._LINE_PREFIX}- /checkpoint rewind <checkpoint_id>")
        else:
            print(
                f"{self._LINE_PREFIX}Memory commands are available when MemoryEnabled=true "
                "(see operations/config.md)."
            )

    async def _handle_memory_command(self, command: str) -> None:
        if not self._user_memory_enabled or not self._user_memory_dir:
            print(f"{self._LINE_PREFIX}User memory commands require UserMemoryEnabled=true")
            return

        parts = command.split()
        memory_dir = Path(self._user_memory_dir)

        if len(parts) == 1:
            memory_file = memory_dir / "MEMORY.md"
            if not memory_file.exists():
                print(f"{self._LINE_PREFIX}No memory file found ({memory_file})")
                return
            content = memory_file.read_text(encoding="utf-8")
            print(f"{self._LINE_PREFIX}Contents of MEMORY.md:\n{content}")
            return

        if len(parts) == 2 and parts[1] == "list":
            if not memory_dir.exists():
                print(f"{self._LINE_PREFIX}No memory files found")
                return
            files = sorted(p.name for p in memory_dir.iterdir() if p.suffix == ".md")
            if not files:
                print(f"{self._LINE_PREFIX}No memory files found")
                return
            print(f"{self._LINE_PREFIX}Memory files:")
            for name in files:
                print(f"{self._LINE_PREFIX}  - {name}")
            return

        if len(parts) == 2 and parts[1] == "edit":
            memory_file = memory_dir / "MEMORY.md"
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
            if not editor:
                print(
                    f"{self._LINE_PREFIX}No $EDITOR set. "
                    f"Edit manually: {memory_file}"
                )
                return
            memory_dir.mkdir(parents=True, exist_ok=True)
            if not memory_file.exists():
                memory_file.write_text("", encoding="utf-8")
            try:
                subprocess.run([editor, str(memory_file)], check=True)
                print(f"{self._LINE_PREFIX}Editor closed.")
            except Exception as ex:
                print(f"{self._LINE_PREFIX}Failed to open editor: {ex}")
            return

        if len(parts) >= 2 and parts[1] == "reset":
            if not memory_dir.exists():
                print(f"{self._LINE_PREFIX}No memory directory to reset")
                return
            if len(parts) == 2:
                files = [p.name for p in memory_dir.iterdir() if p.suffix == ".md"]
                if not files:
                    print(f"{self._LINE_PREFIX}No memory files to reset")
                    return
                print(
                    f"{self._LINE_PREFIX}This will delete {len(files)} memory file(s). "
                    f"Run '/memory reset confirm' to proceed."
                )
                return
            if len(parts) == 3 and parts[2] == "confirm":
                deleted = 0
                for p in memory_dir.iterdir():
                    if p.suffix == ".md":
                        p.unlink()
                        deleted += 1
                if deleted:
                    print(f"{self._LINE_PREFIX}Deleted {deleted} memory file(s).")
                else:
                    print(f"{self._LINE_PREFIX}No memory files to delete.")
                return

        print(f"{self._LINE_PREFIX}Usage: /memory | /memory list | /memory edit | /memory reset")

    # -- /tool command --

    async def _handle_tool_command(self, command: str) -> None:
        parts = command.split()
        if len(parts) == 1:
            self._print_tool_list()
            return
        name_arg = parts[1]
        tool = self._resolve_tool_name(name_arg)
        if tool is None:
            return
        if len(parts) == 2:
            self._print_tool_details(tool)
            return
        sub = parts[2].lower()
        if sub == "schema":
            self._print_tool_schema(tool)
            return
        if sub == "config":
            self._print_tool_config(tool)
            return
        print(
            f"{self._LINE_PREFIX}Usage: /tool | /tool <name> | "
            "/tool <name> schema | /tool <name> config"
        )

    def _resolve_tool_name(self, name_arg: str) -> Tool | None:
        # Exact match first
        if name_arg in self._tool_map:
            return self._tool_map[name_arg]
        # Short-name match: name_arg matches the part after "__"
        matches = [
            t for t in self._tool_map.values()
            if "__" in t.name and t.name.split("__", 1)[1] == name_arg
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"{self._LINE_PREFIX}Ambiguous tool name '{name_arg}'. Matches:")
            for t in sorted(matches, key=lambda t: t.name):
                print(f"{self._LINE_PREFIX}  - {t.name}")
            return None
        print(f"{self._LINE_PREFIX}Tool not found: {name_arg}")
        return None

    def _print_tool_list(self) -> None:
        if not self._tool_map:
            print(f"{self._LINE_PREFIX}No tools loaded.")
            return
        # Group by server prefix
        groups: dict[str, list[str]] = {}
        for name in sorted(self._tool_map):
            if "__" in name:
                server, short = name.split("__", 1)
            else:
                server, short = "(built-in)", name
            groups.setdefault(server, []).append(short)
        for server in sorted(groups):
            print(f"{self._LINE_PREFIX}[{server}]")
            for short in sorted(groups[server]):
                print(f"{self._LINE_PREFIX}  - {short}")

    def _print_tool_details(self, tool: Tool) -> None:
        print(f"{self._LINE_PREFIX}Name: {tool.name}")
        print(f"{self._LINE_PREFIX}Description: {tool.description}")
        print(f"{self._LINE_PREFIX}Mutating: {tool.is_mutating}")

    def _print_tool_schema(self, tool: Tool) -> None:
        print(f"{self._LINE_PREFIX}Input schema:")
        print(json.dumps(tool.input_schema, indent=2))
        if hasattr(tool, "output_schema") and tool.output_schema is not None:
            print(f"{self._LINE_PREFIX}Output schema:")
            print(json.dumps(tool.output_schema, indent=2))

    def _print_tool_config(self, tool: Tool) -> None:
        fmt = self._tool_result_formatter._tool_formatting.get(tool.name)
        if fmt is not None:
            print(f"{self._LINE_PREFIX}ToolFormatting config for {tool.name}:")
            print(json.dumps(fmt, indent=2))
        else:
            print(f"{self._LINE_PREFIX}ToolFormatting config for {tool.name} (using default):")
            print(json.dumps(self._tool_result_formatter._default_format, indent=2))

    # -- /debug command --

    async def _handle_debug_command(self, command: str) -> None:
        parts = command.split()
        if len(parts) >= 2 and parts[1] == "show-api-payload":
            index = 0
            if len(parts) >= 3:
                try:
                    index = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /debug show-api-payload [N]")
                    return
            self._print_api_payload(index)
            return
        print(f"{self._LINE_PREFIX}Usage: /debug show-api-payload [N]")

    def _print_api_payload(self, index: int) -> None:
        from datetime import datetime

        payload = self._api_payload_store.get(index)
        if payload is None:
            if len(self._api_payload_store) == 0:
                print(f"{self._LINE_PREFIX}No API payloads recorded yet.")
            else:
                print(
                    f"{self._LINE_PREFIX}Payload index {index} out of range "
                    f"(0..{len(self._api_payload_store) - 1})."
                )
            return

        ts = datetime.fromtimestamp(payload.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        # Extract last user message text (skip tool_result messages)
        last_user_msg = ""
        for msg in reversed(payload.messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                last_user_msg = content
                break
            if isinstance(content, list):
                # Tool results are list[dict] with type=tool_result; skip those
                if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
                    continue
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                last_user_msg = " ".join(texts)
                break

        # Extract response text (or tool names if pure tool_use)
        response_text = ""
        if payload.response_message:
            resp_content = payload.response_message.get("content", [])
            if isinstance(resp_content, str):
                response_text = resp_content
            elif isinstance(resp_content, list):
                texts = [b.get("text", "") for b in resp_content if isinstance(b, dict) and b.get("type") == "text"]
                tool_names = [b.get("name", "") for b in resp_content if isinstance(b, dict) and b.get("type") == "tool_use"]
                if texts:
                    response_text = " ".join(texts)
                if tool_names:
                    tool_label = "tool_use: " + ", ".join(tool_names)
                    response_text = f"{response_text}  [{tool_label}]" if response_text else f"[{tool_label}]"

        # Usage info
        from micro_x_agent_loop.usage import estimate_cost
        usage_str = "n/a"
        cost_str = ""
        if payload.usage:
            u = payload.usage
            usage_str = f"in={u.input_tokens} out={u.output_tokens}"
            if u.cache_read_input_tokens:
                usage_str += f" cache_read={u.cache_read_input_tokens}"
            if u.cache_creation_input_tokens:
                usage_str += f" cache_create={u.cache_creation_input_tokens}"
            cost = estimate_cost(u)
            cost_str = f"${cost:.6f}" if cost > 0 else "n/a (unknown model)"

        p = self._LINE_PREFIX
        print(f"{p}API Payload #{index} (most recent):" if index == 0 else f"{p}API Payload #{index}:")
        print(f"{p}  Timestamp:    {ts}")
        print(f"{p}  Model:        {payload.model}")
        print(f"{p}  System prompt: {payload.system_prompt[:80]}... ({len(payload.system_prompt)} chars)")
        print(f"{p}  Messages:     {len(payload.messages)}")
        print(f"{p}  Last user msg: {last_user_msg[:80]}")
        print(f"{p}  Tools:        {payload.tools_count}")
        print(f"{p}  Stop reason:  {payload.stop_reason}")
        print(f"{p}  Response:     {response_text[:80]}... ({len(response_text)} chars)")
        print(f"{p}  Usage:        {usage_str}")
        print(f"{p}  Cost:         {cost_str}")

    async def _handle_session_command(self, command: str) -> None:
        sm = self._memory.session_manager
        if not self._memory_enabled or sm is None:
            print(f"{self._LINE_PREFIX}Session commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1:
            active_id = self._memory.active_session_id
            if active_id is None:
                print(f"{self._LINE_PREFIX}Current session: none")
                return
            session = sm.get_session(active_id)
            title = session.get("title", active_id) if session else active_id
            print(
                f"{self._LINE_PREFIX}Current session: {title} "
                f"[{self._session_controller.short_id(active_id)}] (id={active_id})"
            )
            return

        if len(parts) >= 2 and parts[1] == "list":
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /session list [limit]")
                    return
            sessions = sm.list_sessions(limit=limit)
            if not sessions:
                print(f"{self._LINE_PREFIX}No sessions found.")
                return
            print(f"{self._LINE_PREFIX}Recent sessions:")
            for s in sessions:
                print(self._session_controller.format_session_list_entry(
                    s, active_session_id=self._memory.active_session_id
                ))
            return

        if len(parts) >= 2 and parts[1] == "new":
            title = command.partition("new")[2].strip()
            new_id = sm.create_session(title=title if title else None)
            self._memory.active_session_id = new_id
            self._messages = self._memory.load_messages(new_id)
            self._session_accumulator.reset(session_id=new_id)
            self._turn_number = 0
            session = sm.get_session(new_id) or {"title": new_id}
            print(
                f"{self._LINE_PREFIX}Started new session: {session.get('title', new_id)} "
                f"[{self._session_controller.short_id(new_id)}] (id={new_id})"
            )
            return

        if len(parts) >= 3 and parts[1] == "name":
            active_id = self._memory.active_session_id
            if active_id is None:
                print(f"{self._LINE_PREFIX}No active session to name")
                return
            title = command.partition("name")[2].strip()
            if not title:
                print(f"{self._LINE_PREFIX}Usage: /session name <title>")
                return
            sm.set_session_title(active_id, title)
            print(f"{self._LINE_PREFIX}Session named: {title}")
            return

        if len(parts) >= 3 and parts[1] == "resume":
            target = command.partition("resume")[2].strip()
            if not target:
                print(f"{self._LINE_PREFIX}Usage: /session resume <id-or-name>")
                return
            try:
                session = sm.resolve_session_identifier(target)
            except ValueError as ex:
                print(f"{self._LINE_PREFIX}{ex}")
                return
            if session is None:
                print(f"{self._LINE_PREFIX}Session not found: {target}")
                return
            resolved_id = session["id"]
            self._memory.active_session_id = resolved_id
            self._messages = self._memory.load_messages(resolved_id)
            self._session_accumulator.reset(session_id=resolved_id)
            self._turn_number = 0
            summary = sm.build_session_summary(resolved_id)
            print(
                f"{self._LINE_PREFIX}Resumed session {summary['title']} "
                f"[{self._session_controller.short_id(resolved_id)}] (id={resolved_id}, {len(self._messages)} messages)"
            )
            for line in self._session_controller.format_resumed_summary_lines(summary):
                print(line)
            return

        if len(parts) == 2 and parts[1] == "fork":
            active_id = self._memory.active_session_id
            if active_id is None:
                print(f"{self._LINE_PREFIX}No active session to fork")
                return
            source_id = active_id
            fork_id = sm.fork_session(source_id)
            self._memory.active_session_id = fork_id
            self._messages = self._memory.load_messages(fork_id)
            self._session_accumulator.reset(session_id=fork_id)
            self._turn_number = 0
            print(f"{self._LINE_PREFIX}Forked session {source_id} -> {fork_id}")
            return

        print(
            f"{self._LINE_PREFIX}Usage: /session | /session new [title] | /session list [limit] | "
            "/session name <title> | /session resume <id-or-name> | /session fork"
        )

    async def _handle_rewind_command(self, command: str) -> None:
        cm = self._memory.checkpoint_manager
        if not self._memory_enabled or cm is None:
            print(f"{self._LINE_PREFIX}Rewind requires MemoryEnabled=true")
            return
        parts = command.split()
        if len(parts) != 2:
            print(f"{self._LINE_PREFIX}Usage: /rewind <checkpoint_id>")
            return

        checkpoint_id = parts[1]
        try:
            _, outcomes = cm.rewind_files(checkpoint_id)
        except Exception as ex:
            print(f"{self._LINE_PREFIX}Rewind failed: {ex}")
            return

        for line in self._checkpoint_service.format_rewind_outcome_lines(checkpoint_id, outcomes):
            print(line)

    async def _handle_checkpoint_command(self, command: str) -> None:
        cm = self._memory.checkpoint_manager
        active_id = self._memory.active_session_id
        if (
            not self._memory_enabled
            or cm is None
            or active_id is None
        ):
            print(f"{self._LINE_PREFIX}Checkpoint commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1 or (len(parts) >= 2 and parts[1] == "list"):
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /checkpoint list [limit]")
                    return
            checkpoints = cm.list_checkpoints(active_id, limit=limit)
            if not checkpoints:
                print(f"{self._LINE_PREFIX}No checkpoints found for current session.")
                return
            print(f"{self._LINE_PREFIX}Recent checkpoints:")
            for cp in checkpoints:
                print(self._checkpoint_service.format_checkpoint_list_entry(cp))
            return

        if len(parts) == 3 and parts[1] == "rewind":
            await self._handle_rewind_command(f"/rewind {parts[2]}")
            return

        print(
            f"{self._LINE_PREFIX}Usage: /checkpoint list [limit] | /checkpoint rewind <checkpoint_id>"
        )

    async def _handle_voice_command(self, command: str) -> None:
        try:
            parts = parse_voice_command(command)
        except ValueError:
            print(f"{self._LINE_PREFIX}Invalid command syntax")
            return
        if len(parts) == 1:
            print(
                f"{self._LINE_PREFIX}Usage: /voice start [microphone|loopback] "
                "[--mic-device-id <id>] [--mic-device-name <name>] "
                "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
                "/voice status | /voice devices | /voice events [limit] | /voice stop"
            )
            return

        action = parts[1].lower()
        if action == "start":
            opts, error = parse_voice_start_options(parts, line_prefix=self._LINE_PREFIX)
            if error:
                print(error)
                return
            assert opts is not None
            print(
                await self._voice_runtime.start(
                    opts.source,
                    opts.mic_device_id,
                    opts.mic_device_name,
                    opts.chunk_seconds,
                    opts.endpointing_ms,
                    opts.utterance_end_ms,
                )
            )
            return

        if action == "status":
            print(await self._voice_runtime.status())
            return

        if action == "devices":
            print(await self._voice_runtime.devices())
            return

        if action == "events":
            limit = 50
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /voice events [limit]")
                    return
            print(await self._voice_runtime.events(limit))
            return

        if action == "stop":
            print(await self._voice_runtime.stop())
            return

        print(
            f"{self._LINE_PREFIX}Usage: /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
            "/voice status | /voice devices | /voice events [limit] | /voice stop"
        )

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
        await self._voice_runtime.shutdown()

    @property
    def active_session_id(self) -> str | None:
        return self._memory.active_session_id

    # Backward-compatible wrappers for existing tests.
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
