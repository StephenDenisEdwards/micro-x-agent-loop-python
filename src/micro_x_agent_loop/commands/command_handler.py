from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.commands.voice_command import parse_voice_command, parse_voice_start_options
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import SessionAccumulator
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.voice_runtime import VoiceRuntime


class CommandHandler:
    """Implements all slash-command logic, decoupled from Agent state."""

    def __init__(
        self,
        *,
        line_prefix: str,
        session_accumulator: SessionAccumulator,
        memory: ActiveMemoryFacade | NullMemoryFacade,
        memory_enabled: bool,
        tool_map: dict[str, Tool],
        tool_result_formatter: ToolResultFormatter,
        api_payload_store: ApiPayloadStore,
        voice_runtime: VoiceRuntime,
        session_controller: SessionController,
        checkpoint_service: CheckpointService,
        user_memory_enabled: bool,
        user_memory_dir: str,
        on_session_reset: Callable[[str, list[dict]], None],
    ) -> None:
        self._p = line_prefix
        self._session_accumulator = session_accumulator
        self._memory = memory
        self._memory_enabled = memory_enabled
        self._tool_map = tool_map
        self._tool_result_formatter = tool_result_formatter
        self._api_payload_store = api_payload_store
        self._voice_runtime = voice_runtime
        self._session_controller = session_controller
        self._checkpoint_service = checkpoint_service
        self._user_memory_enabled = user_memory_enabled
        self._user_memory_dir = user_memory_dir
        self._on_session_reset = on_session_reset

    # -- /help --

    async def on_help(self) -> None:
        self._print_help()

    def on_unknown_command(self, trimmed: str) -> None:
        print(f"{self._p}Unknown local command: {trimmed}")

    def _print_help(self) -> None:
        p = self._p
        print(f"{p}Available commands:")
        print(f"{p}- /help")
        print(f"{p}- /prompt <filename>")
        print(f"{p}- /cost")
        print(
            f"{p}- /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>]"
        )
        print(f"{p}- /voice status")
        print(f"{p}- /voice devices")
        print(f"{p}- /voice events [limit]")
        print(f"{p}- /voice stop")
        print(f"{p}- /tools mcp")
        print(f"{p}- /tool")
        print(f"{p}- /tool <name>")
        print(f"{p}- /tool <name> schema")
        print(f"{p}- /tool <name> config")
        print(f"{p}- /debug show-api-payload [N]")
        if self._user_memory_enabled:
            print(f"{p}- /memory")
            print(f"{p}- /memory list")
            print(f"{p}- /memory edit")
            print(f"{p}- /memory reset")
        if self._memory_enabled:
            print(f"{p}- /session")
            print(f"{p}- /session new [title]")
            print(f"{p}- /session list [limit]")
            print(f"{p}- /session name <title>")
            print(f"{p}- /session resume <id-or-name>")
            print(f"{p}- /session fork")
            print(f"{p}- /rewind <checkpoint_id>")
            print(f"{p}- /checkpoint list [limit]")
            print(f"{p}- /checkpoint rewind <checkpoint_id>")
        else:
            print(
                f"{p}Memory commands are available when MemoryEnabled=true "
                "(see operations/config.md)."
            )

    # -- /cost --

    async def handle_cost(self, command: str) -> None:
        print(f"{self._p}{self._session_accumulator.format_summary()}")

    # -- /memory --

    async def handle_memory(self, command: str) -> None:
        if not self._user_memory_enabled or not self._user_memory_dir:
            print(f"{self._p}User memory commands require UserMemoryEnabled=true")
            return

        parts = command.split()
        memory_dir = Path(self._user_memory_dir)

        if len(parts) == 1:
            memory_file = memory_dir / "MEMORY.md"
            if not memory_file.exists():
                print(f"{self._p}No memory file found ({memory_file})")
                return
            content = memory_file.read_text(encoding="utf-8")
            print(f"{self._p}Contents of MEMORY.md:\n{content}")
            return

        if len(parts) == 2 and parts[1] == "list":
            if not memory_dir.exists():
                print(f"{self._p}No memory files found")
                return
            files = sorted(p.name for p in memory_dir.iterdir() if p.suffix == ".md")
            if not files:
                print(f"{self._p}No memory files found")
                return
            print(f"{self._p}Memory files:")
            for name in files:
                print(f"{self._p}  - {name}")
            return

        if len(parts) == 2 and parts[1] == "edit":
            memory_file = memory_dir / "MEMORY.md"
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
            if not editor:
                print(
                    f"{self._p}No $EDITOR set. "
                    f"Edit manually: {memory_file}"
                )
                return
            memory_dir.mkdir(parents=True, exist_ok=True)
            if not memory_file.exists():
                memory_file.write_text("", encoding="utf-8")
            try:
                subprocess.run([editor, str(memory_file)], check=True)
                print(f"{self._p}Editor closed.")
            except Exception as ex:
                print(f"{self._p}Failed to open editor: {ex}")
            return

        if len(parts) >= 2 and parts[1] == "reset":
            if not memory_dir.exists():
                print(f"{self._p}No memory directory to reset")
                return
            if len(parts) == 2:
                files = [p.name for p in memory_dir.iterdir() if p.suffix == ".md"]
                if not files:
                    print(f"{self._p}No memory files to reset")
                    return
                print(
                    f"{self._p}This will delete {len(files)} memory file(s). "
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
                    print(f"{self._p}Deleted {deleted} memory file(s).")
                else:
                    print(f"{self._p}No memory files to delete.")
                return

        print(f"{self._p}Usage: /memory | /memory list | /memory edit | /memory reset")

    # -- /tools --

    async def handle_tools(self, command: str) -> None:
        parts = command.split()
        if len(parts) == 2 and parts[1] == "mcp":
            self._print_mcp_tools()
            return
        print(f"{self._p}Usage: /tools mcp")

    def _print_mcp_tools(self) -> None:
        groups: dict[str, list[str]] = {}
        for name in self._tool_map:
            if "__" not in name:
                continue
            server, short = name.split("__", 1)
            groups.setdefault(server, []).append(short)
        if not groups:
            print(f"{self._p}No MCP tools loaded.")
            return
        print(f"{self._p}MCP servers:")
        for server in sorted(groups):
            print(f"{self._p}  {server}:")
            for short in sorted(groups[server]):
                print(f"{self._p}    - {short}")

    # -- /tool --

    async def handle_tool(self, command: str) -> None:
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
            f"{self._p}Usage: /tool | /tool <name> | "
            "/tool <name> schema | /tool <name> config"
        )

    def _resolve_tool_name(self, name_arg: str) -> Tool | None:
        if name_arg in self._tool_map:
            return self._tool_map[name_arg]
        matches = [
            t for t in self._tool_map.values()
            if "__" in t.name and t.name.split("__", 1)[1] == name_arg
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"{self._p}Ambiguous tool name '{name_arg}'. Matches:")
            for t in sorted(matches, key=lambda t: t.name):
                print(f"{self._p}  - {t.name}")
            return None
        print(f"{self._p}Tool not found: {name_arg}")
        return None

    def _print_tool_list(self) -> None:
        if not self._tool_map:
            print(f"{self._p}No tools loaded.")
            return
        groups: dict[str, list[str]] = {}
        for name in sorted(self._tool_map):
            if "__" in name:
                server, short = name.split("__", 1)
            else:
                server, short = "(built-in)", name
            groups.setdefault(server, []).append(short)
        for server in sorted(groups):
            print(f"{self._p}[{server}]")
            for short in sorted(groups[server]):
                print(f"{self._p}  - {short}")

    def _print_tool_details(self, tool: Tool) -> None:
        print(f"{self._p}Name: {tool.name}")
        print(f"{self._p}Description: {tool.description}")
        print(f"{self._p}Mutating: {tool.is_mutating}")

    def _print_tool_schema(self, tool: Tool) -> None:
        print(f"{self._p}Input schema:")
        print(json.dumps(tool.input_schema, indent=2))
        if hasattr(tool, "output_schema") and tool.output_schema is not None:
            print(f"{self._p}Output schema:")
            print(json.dumps(tool.output_schema, indent=2))

    def _print_tool_config(self, tool: Tool) -> None:
        fmt = self._tool_result_formatter.get_tool_format(tool.name)
        if fmt is not None:
            print(f"{self._p}ToolFormatting config for {tool.name}:")
            print(json.dumps(fmt, indent=2))
        else:
            print(f"{self._p}ToolFormatting config for {tool.name} (using default):")
            print(json.dumps(self._tool_result_formatter.default_format, indent=2))

    # -- /debug --

    async def handle_debug(self, command: str) -> None:
        parts = command.split()
        if len(parts) >= 2 and parts[1] == "show-api-payload":
            index = 0
            if len(parts) >= 3:
                try:
                    index = int(parts[2])
                except ValueError:
                    print(f"{self._p}Usage: /debug show-api-payload [N]")
                    return
            self._print_api_payload(index)
            return
        print(f"{self._p}Usage: /debug show-api-payload [N]")

    def _print_api_payload(self, index: int) -> None:
        from datetime import datetime

        payload = self._api_payload_store.get(index)
        if payload is None:
            if len(self._api_payload_store) == 0:
                print(f"{self._p}No API payloads recorded yet.")
            else:
                print(
                    f"{self._p}Payload index {index} out of range "
                    f"(0..{len(self._api_payload_store) - 1})."
                )
            return

        ts = datetime.fromtimestamp(payload.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        last_user_msg = ""
        for msg in reversed(payload.messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                last_user_msg = content
                break
            if isinstance(content, list):
                if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
                    continue
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                last_user_msg = " ".join(texts)
                break

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

        p = self._p
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

    # -- /session --

    async def handle_session(self, command: str) -> None:
        sm = self._memory.session_manager
        if not self._memory_enabled or sm is None:
            print(f"{self._p}Session commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1:
            active_id = self._memory.active_session_id
            if active_id is None:
                print(f"{self._p}Current session: none")
                return
            session = sm.get_session(active_id)
            title = session.get("title", active_id) if session else active_id
            print(
                f"{self._p}Current session: {title} "
                f"[{self._session_controller.short_id(active_id)}] (id={active_id})"
            )
            return

        if len(parts) >= 2 and parts[1] == "list":
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._p}Usage: /session list [limit]")
                    return
            sessions = sm.list_sessions(limit=limit)
            if not sessions:
                print(f"{self._p}No sessions found.")
                return
            print(f"{self._p}Recent sessions:")
            for s in sessions:
                print(self._session_controller.format_session_list_entry(
                    s, active_session_id=self._memory.active_session_id
                ))
            return

        if len(parts) >= 2 and parts[1] == "new":
            title = command.partition("new")[2].strip()
            new_id = sm.create_session(title=title if title else None)
            self._memory.active_session_id = new_id
            self._on_session_reset(new_id, self._memory.load_messages(new_id))
            session = sm.get_session(new_id) or {"title": new_id}
            print(
                f"{self._p}Started new session: {session.get('title', new_id)} "
                f"[{self._session_controller.short_id(new_id)}] (id={new_id})"
            )
            return

        if len(parts) >= 3 and parts[1] == "name":
            active_id = self._memory.active_session_id
            if active_id is None:
                print(f"{self._p}No active session to name")
                return
            title = command.partition("name")[2].strip()
            if not title:
                print(f"{self._p}Usage: /session name <title>")
                return
            sm.set_session_title(active_id, title)
            print(f"{self._p}Session named: {title}")
            return

        if len(parts) >= 3 and parts[1] == "resume":
            target = command.partition("resume")[2].strip()
            if not target:
                print(f"{self._p}Usage: /session resume <id-or-name>")
                return
            try:
                session = sm.resolve_session_identifier(target)
            except ValueError as ex:
                print(f"{self._p}{ex}")
                return
            if session is None:
                print(f"{self._p}Session not found: {target}")
                return
            resolved_id = session["id"]
            self._memory.active_session_id = resolved_id
            new_messages = self._memory.load_messages(resolved_id)
            self._on_session_reset(resolved_id, new_messages)
            summary = sm.build_session_summary(resolved_id)
            print(
                f"{self._p}Resumed session {summary['title']} "
                f"[{self._session_controller.short_id(resolved_id)}] (id={resolved_id}, {len(new_messages)} messages)"
            )
            for line in self._session_controller.format_resumed_summary_lines(summary):
                print(line)
            return

        if len(parts) == 2 and parts[1] == "fork":
            active_id = self._memory.active_session_id
            if active_id is None:
                print(f"{self._p}No active session to fork")
                return
            source_id = active_id
            fork_id = sm.fork_session(source_id)
            self._memory.active_session_id = fork_id
            self._on_session_reset(fork_id, self._memory.load_messages(fork_id))
            print(f"{self._p}Forked session {source_id} -> {fork_id}")
            return

        print(
            f"{self._p}Usage: /session | /session new [title] | /session list [limit] | "
            "/session name <title> | /session resume <id-or-name> | /session fork"
        )

    # -- /rewind --

    async def handle_rewind(self, command: str) -> None:
        cm = self._memory.checkpoint_manager
        if not self._memory_enabled or cm is None:
            print(f"{self._p}Rewind requires MemoryEnabled=true")
            return
        parts = command.split()
        if len(parts) != 2:
            print(f"{self._p}Usage: /rewind <checkpoint_id>")
            return

        checkpoint_id = parts[1]
        try:
            _, outcomes = cm.rewind_files(checkpoint_id)
        except Exception as ex:
            print(f"{self._p}Rewind failed: {ex}")
            return

        for line in self._checkpoint_service.format_rewind_outcome_lines(checkpoint_id, outcomes):
            print(line)

    # -- /checkpoint --

    async def handle_checkpoint(self, command: str) -> None:
        cm = self._memory.checkpoint_manager
        active_id = self._memory.active_session_id
        if (
            not self._memory_enabled
            or cm is None
            or active_id is None
        ):
            print(f"{self._p}Checkpoint commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1 or (len(parts) >= 2 and parts[1] == "list"):
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._p}Usage: /checkpoint list [limit]")
                    return
            checkpoints = cm.list_checkpoints(active_id, limit=limit)
            if not checkpoints:
                print(f"{self._p}No checkpoints found for current session.")
                return
            print(f"{self._p}Recent checkpoints:")
            for cp in checkpoints:
                print(self._checkpoint_service.format_checkpoint_list_entry(cp))
            return

        if len(parts) == 3 and parts[1] == "rewind":
            await self.handle_rewind(f"/rewind {parts[2]}")
            return

        print(
            f"{self._p}Usage: /checkpoint list [limit] | /checkpoint rewind <checkpoint_id>"
        )

    # -- /voice --

    async def handle_voice(self, command: str) -> None:
        try:
            parts = parse_voice_command(command)
        except ValueError:
            print(f"{self._p}Invalid command syntax")
            return
        if len(parts) == 1:
            print(
                f"{self._p}Usage: /voice start [microphone|loopback] "
                "[--mic-device-id <id>] [--mic-device-name <name>] "
                "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
                "/voice status | /voice devices | /voice events [limit] | /voice stop"
            )
            return

        action = parts[1].lower()
        if action == "start":
            opts, error = parse_voice_start_options(parts, line_prefix=self._p)
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
                    print(f"{self._p}Usage: /voice events [limit]")
                    return
            print(await self._voice_runtime.events(limit))
            return

        if action == "stop":
            print(await self._voice_runtime.stop())
            return

        print(
            f"{self._p}Usage: /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
            "/voice status | /voice devices | /voice events [limit] | /voice stop"
        )
