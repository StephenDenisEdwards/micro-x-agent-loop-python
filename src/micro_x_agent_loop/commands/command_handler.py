from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore
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
        voice_runtime: VoiceRuntime | None,
        session_controller: SessionController,
        checkpoint_service: CheckpointService,
        user_memory_enabled: bool,
        user_memory_dir: str,
        prompt_command_store: PromptCommandStore,
        on_session_reset: Callable[[str, list[dict]], None],
        on_tools_deleted: Callable[[list[str]], None] | None = None,
        output: Callable[[str], None] = print,
        routing_feedback_store: object | None = None,
    ) -> None:
        self._p = line_prefix
        self._print = output
        self._prompt_command_store = prompt_command_store
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
        self._on_tools_deleted = on_tools_deleted or (lambda _tool_names: None)
        self._routing_feedback_store = routing_feedback_store

    # -- /help --

    async def on_help(self) -> None:
        self._print_help()

    def on_unknown_command(self, trimmed: str) -> None:
        self._print(f"{self._p}Unknown local command: {trimmed}")

    def _print_help(self) -> None:
        p = self._p
        self._print(f"{p}Available commands:")
        self._print(f"{p}- /help")
        self._print(f"{p}- /prompt <filename>")
        self._print(f"{p}- /command")
        self._print(f"{p}- /command <name> [arguments]")
        self._print(f"{p}- /cost")
        self._print(f"{p}- /cost reconcile [days] [--start YYYY-MM-DD] [--end YYYY-MM-DD]")
        self._print(
            f"{p}- /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>]"
        )
        self._print(f"{p}- /voice status")
        self._print(f"{p}- /voice devices")
        self._print(f"{p}- /voice events [limit]")
        self._print(f"{p}- /voice stop")
        self._print(f"{p}- /tools mcp")
        self._print(f"{p}- /tool")
        self._print(f"{p}- /tool <name>")
        self._print(f"{p}- /tool <name> schema")
        self._print(f"{p}- /tool <name> config")
        self._print(f"{p}- /tool delete <name>")
        self._print(f"{p}- /routing")
        self._print(f"{p}- /routing tasks | providers | stages | recent")
        self._print(f"{p}- /console-log-level [TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL|OFF]")
        self._print(f"{p}- /debug show-api-payload [N]")
        if self._user_memory_enabled:
            self._print(f"{p}- /memory")
            self._print(f"{p}- /memory list")
            self._print(f"{p}- /memory edit")
            self._print(f"{p}- /memory reset")
        if self._memory_enabled:
            self._print(f"{p}- /session")
            self._print(f"{p}- /session new [title]")
            self._print(f"{p}- /session list [limit]")
            self._print(f"{p}- /session name <title>")
            self._print(f"{p}- /session resume <id-or-name>")
            self._print(f"{p}- /session fork")
            self._print(f"{p}- /rewind <checkpoint_id>")
            self._print(f"{p}- /checkpoint list [limit]")
            self._print(f"{p}- /checkpoint rewind <checkpoint_id>")
        else:
            self._print(
                f"{p}Memory commands are available when MemoryEnabled=true "
                "(see operations/config.md)."
            )

    # -- /command --

    async def handle_command(self, command: str) -> str | None:
        """Handle /command. Returns prompt text to execute, or None if handled locally."""
        parts = command.split(None, 2)
        if len(parts) == 1:
            self._print_command_list()
            return None

        name = parts[1]
        prompt = self._prompt_command_store.load_command(name)
        if prompt is None:
            self._print(f"{self._p}Unknown command: {name}")
            self._print_command_list()
            return None

        arguments = parts[2] if len(parts) > 2 else ""
        prompt = prompt.replace("$ARGUMENTS", arguments)
        return prompt

    def _print_command_list(self) -> None:
        commands = self._prompt_command_store.list_commands()
        if not commands:
            self._print(f"{self._p}No commands found. Add .md files to the .commands/ directory.")
            return
        max_name = max(len(name) for name, _ in commands)
        self._print(f"{self._p}Available commands:")
        for name, description in commands:
            self._print(f"{self._p}  {name:<{max_name}}  {description}")

    # -- /console-log-level --

    async def handle_console_log_level(self, command: str) -> None:
        from micro_x_agent_loop.logging_config import ConsoleLogConsumer

        consumer = ConsoleLogConsumer.get_instance()
        if consumer is None:
            self._print(f"{self._p}No console log consumer is active.")
            return

        parts = command.split()
        if len(parts) == 1:
            self._print(f"{self._p}Console log level: {consumer.level}")
            return

        valid_levels = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL", "OFF")
        new_level = parts[1].upper()
        if new_level not in valid_levels:
            self._print(f"{self._p}Invalid level: {parts[1]}. Valid: {', '.join(valid_levels)}")
            return

        consumer.set_level(new_level)
        self._print(f"{self._p}Console log level set to {new_level}")

    # -- /cost --

    async def handle_cost(self, command: str) -> None:
        parts = command.split()
        if len(parts) >= 2 and parts[1] == "reconcile":
            await self._handle_cost_reconcile(parts)
            return
        self._print(f"{self._p}{self._session_accumulator.format_summary()}")

    async def _handle_cost_reconcile(self, parts: list[str]) -> None:
        from micro_x_agent_loop.cost_reconciliation import reconcile_costs

        days = 1
        start: str | None = None
        end: str | None = None

        # Parse args: positional days, or --start/--end flags
        i = 2
        while i < len(parts):
            arg = parts[i]
            if arg in ("--start", "--from") and i + 1 < len(parts):
                start = parts[i + 1]
                i += 2
            elif arg in ("--end", "--to") and i + 1 < len(parts):
                end = parts[i + 1]
                i += 2
            else:
                try:
                    days = int(arg)
                except ValueError:
                    self._print(
                        f"{self._p}Usage: /cost reconcile [days] [--start YYYY-MM-DD] [--end YYYY-MM-DD]"
                    )
                    return
                i += 1

        store = self._memory.store
        try:
            lines = await reconcile_costs(self._tool_map, store, days=days, start=start, end=end)
        except ValueError as ex:
            self._print(f"{self._p}Invalid date format: {ex}")
            self._print(f"{self._p}Use YYYY-MM-DD (e.g. 2026-03-01)")
            return
        for line in lines:
            self._print(f"{self._p}{line}")

    # -- /memory --

    async def handle_memory(self, command: str) -> None:
        if not self._user_memory_enabled or not self._user_memory_dir:
            self._print(f"{self._p}User memory commands require UserMemoryEnabled=true")
            return

        parts = command.split()
        memory_dir = Path(self._user_memory_dir)

        if len(parts) == 1:
            memory_file = memory_dir / "MEMORY.md"
            if not memory_file.exists():
                self._print(f"{self._p}No memory file found ({memory_file})")
                return
            content = memory_file.read_text(encoding="utf-8")
            self._print(f"{self._p}Contents of MEMORY.md:\n{content}")
            return

        if len(parts) == 2 and parts[1] == "list":
            if not memory_dir.exists():
                self._print(f"{self._p}No memory files found")
                return
            files = sorted(p.name for p in memory_dir.iterdir() if p.suffix == ".md")
            if not files:
                self._print(f"{self._p}No memory files found")
                return
            self._print(f"{self._p}Memory files:")
            for name in files:
                self._print(f"{self._p}  - {name}")
            return

        if len(parts) == 2 and parts[1] == "edit":
            memory_file = memory_dir / "MEMORY.md"
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
            if not editor:
                self._print(
                    f"{self._p}No $EDITOR set. "
                    f"Edit manually: {memory_file}"
                )
                return
            memory_dir.mkdir(parents=True, exist_ok=True)
            if not memory_file.exists():
                memory_file.write_text("", encoding="utf-8")
            try:
                subprocess.run([editor, str(memory_file)], check=True)
                self._print(f"{self._p}Editor closed.")
            except Exception as ex:
                self._print(f"{self._p}Failed to open editor: {ex}")
            return

        if len(parts) >= 2 and parts[1] == "reset":
            if not memory_dir.exists():
                self._print(f"{self._p}No memory directory to reset")
                return
            if len(parts) == 2:
                files = [p.name for p in memory_dir.iterdir() if p.suffix == ".md"]
                if not files:
                    self._print(f"{self._p}No memory files to reset")
                    return
                self._print(
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
                    self._print(f"{self._p}Deleted {deleted} memory file(s).")
                else:
                    self._print(f"{self._p}No memory files to delete.")
                return

        self._print(f"{self._p}Usage: /memory | /memory list | /memory edit | /memory reset")

    # -- /tools --

    async def handle_tools(self, command: str) -> None:
        parts = command.split()
        if len(parts) == 2 and parts[1] == "mcp":
            self._print_mcp_tools()
            return
        self._print(f"{self._p}Usage: /tools mcp")

    def _print_mcp_tools(self) -> None:
        groups: dict[str, list[str]] = {}
        for name in self._tool_map:
            if "__" not in name:
                continue
            server, short = name.split("__", 1)
            groups.setdefault(server, []).append(short)
        if not groups:
            self._print(f"{self._p}No MCP tools loaded.")
            return
        self._print(f"{self._p}MCP servers:")
        for server in sorted(groups):
            self._print(f"{self._p}  {server}:")
            for short in sorted(groups[server]):
                self._print(f"{self._p}    - {short}")

    # -- /tool --

    async def handle_tool(self, command: str) -> None:
        parts = command.split()
        if len(parts) == 1:
            self._print_tool_list()
            return
        if len(parts) == 3 and parts[1].lower() == "delete":
            await self._delete_generated_tool(parts[2])
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
        self._print(
            f"{self._p}Usage: /tool | /tool <name> | "
            "/tool <name> schema | /tool <name> config | /tool delete <name>"
        )

    async def _delete_generated_tool(self, name_arg: str) -> None:
        project_root = Path.cwd()
        manifest_path = project_root / "tools" / "manifest.json"
        if not manifest_path.exists():
            self._print(f"{self._p}No generated tool manifest found: {manifest_path}")
            return

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as ex:
            self._print(f"{self._p}Failed to read manifest: {ex}")
            return

        if not isinstance(manifest, dict):
            self._print(f"{self._p}Manifest format is invalid.")
            return

        task_name = self._resolve_manifest_task_name(manifest, name_arg)
        if task_name is None:
            return

        entry = manifest.pop(task_name)
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        except Exception as ex:
            self._print(f"{self._p}Failed to update manifest: {ex}")
            return

        task_dir = self._resolve_manifest_task_dir(project_root, task_name, entry)
        dir_removed = False
        if task_dir is not None and task_dir.exists():
            shutil.rmtree(task_dir)
            dir_removed = True

        deleted_tool_names = [
            tool_name for tool_name in list(self._tool_map)
            if tool_name == task_name or tool_name.startswith(f"{task_name}__")
        ]
        for tool_name in deleted_tool_names:
            self._tool_map.pop(tool_name, None)
        self._on_tools_deleted(deleted_tool_names)

        self._print(f"{self._p}Deleted generated task: {task_name}")
        self._print(f"{self._p}Manifest updated: {manifest_path}")
        if task_dir is not None:
            if dir_removed:
                self._print(f"{self._p}Removed task directory: {task_dir}")
            else:
                self._print(f"{self._p}Task directory not found: {task_dir}")

    def _resolve_manifest_task_name(
        self,
        manifest: dict[str, dict],
        name_arg: str,
    ) -> str | None:
        if name_arg in manifest:
            return name_arg

        matches: list[str] = []
        for task_name, entry in manifest.items():
            tool_name = str(entry.get("tool_name", task_name))
            proxy_name = f"{task_name}__{tool_name}"
            if name_arg in {tool_name, proxy_name}:
                matches.append(task_name)

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            self._print(f"{self._p}Ambiguous generated task name '{name_arg}'. Matches:")
            for task_name in sorted(matches):
                self._print(f"{self._p}  - {task_name}")
            return None

        self._print(f"{self._p}Generated task not found: {name_arg}")
        return None

    def _resolve_manifest_task_dir(
        self,
        project_root: Path,
        task_name: str,
        entry: dict,
    ) -> Path | None:
        server = entry.get("server", {})
        cwd = server.get("cwd") if isinstance(server, dict) else None
        if isinstance(cwd, str) and cwd.strip():
            candidate = (project_root / cwd).resolve()
        else:
            candidate = (project_root / "tools" / task_name).resolve()

        tools_root = (project_root / "tools").resolve()
        try:
            candidate.relative_to(tools_root)
        except ValueError:
            self._print(f"{self._p}Refusing to delete directory outside tools/: {candidate}")
            return None
        return candidate

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
            self._print(f"{self._p}Ambiguous tool name '{name_arg}'. Matches:")
            for t in sorted(matches, key=lambda t: t.name):
                self._print(f"{self._p}  - {t.name}")
            return None
        self._print(f"{self._p}Tool not found: {name_arg}")
        return None

    def _print_tool_list(self) -> None:
        if not self._tool_map:
            self._print(f"{self._p}No tools loaded.")
            return
        groups: dict[str, list[str]] = {}
        for name in sorted(self._tool_map):
            if "__" in name:
                server, short = name.split("__", 1)
            else:
                server, short = "(built-in)", name
            groups.setdefault(server, []).append(short)
        for server in sorted(groups):
            self._print(f"{self._p}[{server}]")
            for short in sorted(groups[server]):
                self._print(f"{self._p}  - {short}")

    def _print_tool_details(self, tool: Tool) -> None:
        self._print(f"{self._p}Name: {tool.name}")
        self._print(f"{self._p}Description: {tool.description}")
        self._print(f"{self._p}Mutating: {tool.is_mutating}")

    def _print_tool_schema(self, tool: Tool) -> None:
        self._print(f"{self._p}Input schema:")
        self._print(json.dumps(tool.input_schema, indent=2))
        if hasattr(tool, "output_schema") and tool.output_schema is not None:
            self._print(f"{self._p}Output schema:")
            self._print(json.dumps(tool.output_schema, indent=2))

    def _print_tool_config(self, tool: Tool) -> None:
        fmt = self._tool_result_formatter.get_tool_format(tool.name)
        if fmt is not None:
            self._print(f"{self._p}ToolFormatting config for {tool.name}:")
            self._print(json.dumps(fmt, indent=2))
        else:
            self._print(f"{self._p}ToolFormatting config for {tool.name} (using default):")
            self._print(json.dumps(self._tool_result_formatter.default_format, indent=2))

    # -- /debug --

    async def handle_debug(self, command: str) -> None:
        parts = command.split()
        if len(parts) >= 2 and parts[1] == "show-api-payload":
            index = 0
            if len(parts) >= 3:
                try:
                    index = int(parts[2])
                except ValueError:
                    self._print(f"{self._p}Usage: /debug show-api-payload [N]")
                    return
            self._print_api_payload(index)
            return
        self._print(f"{self._p}Usage: /debug show-api-payload [N]")

    def _print_api_payload(self, index: int) -> None:
        from datetime import datetime

        payload = self._api_payload_store.get(index)
        if payload is None:
            if len(self._api_payload_store) == 0:
                self._print(f"{self._p}No API payloads recorded yet.")
            else:
                self._print(
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
        self._print(f"{p}API Payload #{index} (most recent):" if index == 0 else f"{p}API Payload #{index}:")
        self._print(f"{p}  Timestamp:    {ts}")
        self._print(f"{p}  Model:        {payload.model}")
        self._print(f"{p}  System prompt: {payload.system_prompt[:80]}... ({len(payload.system_prompt)} chars)")
        self._print(f"{p}  Messages:     {len(payload.messages)}")
        self._print(f"{p}  Last user msg: {last_user_msg[:80]}")
        self._print(f"{p}  Tools:        {payload.tools_count}")
        self._print(f"{p}  Stop reason:  {payload.stop_reason}")
        self._print(f"{p}  Response:     {response_text[:80]}... ({len(response_text)} chars)")
        self._print(f"{p}  Usage:        {usage_str}")
        self._print(f"{p}  Cost:         {cost_str}")

    # -- /session --

    async def handle_session(self, command: str) -> None:
        sm = self._memory.session_manager
        if not self._memory_enabled or sm is None:
            self._print(f"{self._p}Session commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1:
            active_id = self._memory.active_session_id
            if active_id is None:
                self._print(f"{self._p}Current session: none")
                return
            session = sm.get_session(active_id)
            title = session.get("title", active_id) if session else active_id
            self._print(
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
                    self._print(f"{self._p}Usage: /session list [limit]")
                    return
            sessions = sm.list_sessions(limit=limit)
            if not sessions:
                self._print(f"{self._p}No sessions found.")
                return
            self._print(f"{self._p}Recent sessions:")
            for s in sessions:
                self._print(self._session_controller.format_session_list_entry(
                    s, active_session_id=self._memory.active_session_id
                ))
            return

        if len(parts) >= 2 and parts[1] == "new":
            title = command.partition("new")[2].strip()
            new_id = sm.create_session(title=title if title else None)
            self._memory.active_session_id = new_id
            self._on_session_reset(new_id, self._memory.load_messages(new_id))
            session = sm.get_session(new_id) or {"title": new_id}
            self._print(
                f"{self._p}Started new session: {session.get('title', new_id)} "
                f"[{self._session_controller.short_id(new_id)}] (id={new_id})"
            )
            return

        if len(parts) >= 3 and parts[1] == "name":
            active_id = self._memory.active_session_id
            if active_id is None:
                self._print(f"{self._p}No active session to name")
                return
            title = command.partition("name")[2].strip()
            if not title:
                self._print(f"{self._p}Usage: /session name <title>")
                return
            sm.set_session_title(active_id, title)
            self._print(f"{self._p}Session named: {title}")
            return

        if len(parts) >= 3 and parts[1] == "resume":
            target = command.partition("resume")[2].strip()
            if not target:
                self._print(f"{self._p}Usage: /session resume <id-or-name>")
                return
            try:
                session = sm.resolve_session_identifier(target)
            except ValueError as ex:
                self._print(f"{self._p}{ex}")
                return
            if session is None:
                self._print(f"{self._p}Session not found: {target}")
                return
            resolved_id = session["id"]
            self._memory.active_session_id = resolved_id
            new_messages = self._memory.load_messages(resolved_id)
            self._on_session_reset(resolved_id, new_messages)
            summary = sm.build_session_summary(resolved_id)
            self._print(
                f"{self._p}Resumed session {summary['title']} "
                f"[{self._session_controller.short_id(resolved_id)}] (id={resolved_id}, {len(new_messages)} messages)"
            )
            for line in self._session_controller.format_resumed_summary_lines(summary):
                self._print(line)
            return

        if len(parts) == 2 and parts[1] == "fork":
            active_id = self._memory.active_session_id
            if active_id is None:
                self._print(f"{self._p}No active session to fork")
                return
            source_id = active_id
            fork_id = sm.fork_session(source_id)
            self._memory.active_session_id = fork_id
            self._on_session_reset(fork_id, self._memory.load_messages(fork_id))
            self._print(f"{self._p}Forked session {source_id} -> {fork_id}")
            return

        self._print(
            f"{self._p}Usage: /session | /session new [title] | /session list [limit] | "
            "/session name <title> | /session resume <id-or-name> | /session fork"
        )

    # -- /rewind --

    async def handle_rewind(self, command: str) -> None:
        cm = self._memory.checkpoint_manager
        if not self._memory_enabled or cm is None:
            self._print(f"{self._p}Rewind requires MemoryEnabled=true")
            return
        parts = command.split()
        if len(parts) != 2:
            self._print(f"{self._p}Usage: /rewind <checkpoint_id>")
            return

        checkpoint_id = parts[1]
        try:
            _, outcomes = cm.rewind_files(checkpoint_id)
        except Exception as ex:
            self._print(f"{self._p}Rewind failed: {ex}")
            return

        for line in self._checkpoint_service.format_rewind_outcome_lines(checkpoint_id, outcomes):
            self._print(line)

    # -- /checkpoint --

    async def handle_checkpoint(self, command: str) -> None:
        cm = self._memory.checkpoint_manager
        active_id = self._memory.active_session_id
        if (
            not self._memory_enabled
            or cm is None
            or active_id is None
        ):
            self._print(f"{self._p}Checkpoint commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1 or (len(parts) >= 2 and parts[1] == "list"):
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    self._print(f"{self._p}Usage: /checkpoint list [limit]")
                    return
            checkpoints = cm.list_checkpoints(active_id, limit=limit)
            if not checkpoints:
                self._print(f"{self._p}No checkpoints found for current session.")
                return
            self._print(f"{self._p}Recent checkpoints:")
            for cp in checkpoints:
                self._print(self._checkpoint_service.format_checkpoint_list_entry(cp))
            return

        if len(parts) == 3 and parts[1] == "rewind":
            await self.handle_rewind(f"/rewind {parts[2]}")
            return

        self._print(
            f"{self._p}Usage: /checkpoint list [limit] | /checkpoint rewind <checkpoint_id>"
        )

    # -- /routing --

    async def handle_routing(self, command: str) -> None:
        if self._routing_feedback_store is None:
            self._print(
                f"{self._p}Routing stats require SemanticRoutingEnabled=true "
                "and RoutingFeedbackEnabled=true"
            )
            return

        from micro_x_agent_loop.routing_feedback import RoutingFeedbackStore
        store: RoutingFeedbackStore = self._routing_feedback_store  # type: ignore[assignment]

        parts = command.split()
        sub = parts[1] if len(parts) >= 2 else ""

        if sub == "tasks":
            stats = store.get_task_type_stats()
            if not stats:
                self._print(f"{self._p}No routing data recorded yet.")
                return
            self._print(f"{self._p}Routing stats by task type:")
            self._print(f"{self._p}{'Task Type':<20s} {'Count':>6s} {'Avg Cost':>10s} {'Avg Latency':>12s} {'Avg Conf':>9s} {'+ / -':>7s}")
            for s in stats:
                self._print(
                    f"{self._p}{s['task_type']:<20s} {s['total']:>6d} "
                    f"${s['avg_cost']:.4f}  {s['avg_latency']:>8.0f} ms  "
                    f"{s['avg_confidence']:.2f}   "
                    f"{s['positive_signals']:>3d}/{s['negative_signals']:<3d}"
                )
            return

        if sub == "providers":
            stats = store.get_provider_stats()
            if not stats:
                self._print(f"{self._p}No routing data recorded yet.")
                return
            self._print(f"{self._p}Routing stats by provider:")
            self._print(f"{self._p}{'Provider':<15s} {'Count':>6s} {'Avg Cost':>10s} {'Avg Latency':>12s} {'Errors':>7s} {'Total Cost':>11s}")
            for s in stats:
                self._print(
                    f"{self._p}{s['provider']:<15s} {s['total']:>6d} "
                    f"${s['avg_cost']:.4f}  {s['avg_latency']:>8.0f} ms  "
                    f"{s['errors']:>7d} ${s['total_cost']:.4f}"
                )
            return

        if sub == "stages":
            stats = store.get_stage_stats()
            if not stats:
                self._print(f"{self._p}No routing data recorded yet.")
                return
            self._print(f"{self._p}Classification stage breakdown:")
            for s in stats:
                self._print(
                    f"{self._p}  {s['stage']}: {s['total']} calls "
                    f"({s['percentage']:.1f}%), avg confidence {s['avg_confidence']:.2f}"
                )
            return

        if sub == "recent":
            outcomes = store.get_recent_outcomes(20)
            if not outcomes:
                self._print(f"{self._p}No routing data recorded yet.")
                return
            self._print(f"{self._p}Recent routing decisions:")
            for o in outcomes:
                self._print(
                    f"{self._p}  T{o['turn_number']} {o['task_type']:<18s} "
                    f"{o['provider']}/{o['model']:<20s} "
                    f"stage={o['stage']} conf={o['confidence']:.2f} "
                    f"${o['cost_usd']:.4f}"
                )
            return

        # Default: summary view
        task_stats = store.get_task_type_stats()
        if not task_stats:
            self._print(f"{self._p}No routing data recorded yet.")
            self._print(f"{self._p}Usage: /routing | /routing tasks | /routing providers | /routing stages | /routing recent")
            return

        total_calls = sum(s["total"] for s in task_stats)
        total_cost = sum(s["total_cost"] for s in task_stats)
        self._print(f"{self._p}Semantic Routing Summary")
        self._print(f"{self._p}  Total routed calls: {total_calls}")
        self._print(f"{self._p}  Total routed cost:  ${total_cost:.4f}")
        self._print(f"{self._p}  Task types active:  {len(task_stats)}")

        stage_stats = store.get_stage_stats()
        for s in stage_stats:
            self._print(
                f"{self._p}  Stage {s['stage']}: {s['percentage']:.1f}% of calls"
            )

        # Adaptive thresholds
        thresholds = store.get_adaptive_thresholds()
        if thresholds:
            self._print(f"{self._p}  Adaptive thresholds (task types with history):")
            for task_type, threshold in sorted(thresholds.items()):
                self._print(f"{self._p}    {task_type}: {threshold:.2f}")

        self._print(f"{self._p}Use /routing tasks|providers|stages|recent for details.")

    # -- /voice --

    async def handle_voice(self, command: str) -> None:
        try:
            parts = parse_voice_command(command)
        except ValueError:
            self._print(f"{self._p}Invalid command syntax")
            return
        if len(parts) == 1:
            self._print(
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
                self._print(error)
                return
            assert opts is not None
            self._print(
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
            self._print(await self._voice_runtime.status())
            return

        if action == "devices":
            self._print(await self._voice_runtime.devices())
            return

        if action == "events":
            limit = 50
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    self._print(f"{self._p}Usage: /voice events [limit]")
                    return
            self._print(await self._voice_runtime.events(limit))
            return

        if action == "stop":
            self._print(await self._voice_runtime.stop())
            return

        self._print(
            f"{self._p}Usage: /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
            "/voice status | /voice devices | /voice events [limit] | /voice stop"
        )
