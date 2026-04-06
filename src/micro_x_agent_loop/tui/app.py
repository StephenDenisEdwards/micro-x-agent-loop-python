"""AgentTUI — Textual-based terminal UI for the micro-x agent."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal
from textual.widgets import Header, Input, Static

from micro_x_agent_loop.app_config import AppConfig
from micro_x_agent_loop.bootstrap import AppRuntime
from micro_x_agent_loop.tui.channel import TextualChannel
from micro_x_agent_loop.tui.screens.ask_user_modal import AskUserModal
from micro_x_agent_loop.tui.widgets.chat_log import ChatLog
from micro_x_agent_loop.tui.widgets.log_panel import LogPanel
from micro_x_agent_loop.tui.widgets.session_sidebar import SessionSidebar
from micro_x_agent_loop.tui.widgets.status_bar import StatusBar
from micro_x_agent_loop.tui.widgets.task_panel import TaskPanel
from micro_x_agent_loop.tui.widgets.tool_panel import ToolPanel

_NO_RESPONSE_MSG = (
    "No response from human — question timed out. "
    "Proceed with your best judgement or report that you cannot continue."
)

# -- 5.1: Command Palette Provider --

# Slash commands available in the palette
_SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show available commands"),
    ("/cost", "Show session cost breakdown"),
    ("/cost reconcile", "Reconcile costs with provider API"),
    ("/session", "Show current session info"),
    ("/session list", "List recent sessions"),
    ("/session new", "Start a new session"),
    ("/session fork", "Fork the current session"),
    ("/tools mcp", "List loaded MCP tools"),
    ("/routing", "Show routing configuration"),
    ("/routing tasks", "Show task type statistics"),
    ("/routing recent", "Show recent routing decisions"),
    ("/compact", "Force conversation compaction"),
    ("/memory", "Show user memory status"),
    ("/memory list", "List user memory files"),
    ("/debug show-api-payload", "Show last API payload"),
    ("/tasks", "Toggle task decomposition panel"),
]

# Available Textual themes
_THEMES: list[str] = [
    "textual-dark",
    "textual-light",
    "nord",
    "gruvbox",
    "catppuccin-mocha",
    "catppuccin-latte",
    "dracula",
    "tokyo-night",
    "monokai",
    "solarized-light",
]


class SlashCommandProvider(Provider):
    """Command palette provider for slash commands."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        # Slash commands
        for cmd, description in _SLASH_COMMANDS:
            score = matcher.match(f"{cmd} {description}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(f"{cmd} — {description}"),
                    command=self._make_command_callback(cmd),
                    help=description,
                )
        # Theme switcher
        for theme_name in _THEMES:
            label = f"Theme: {theme_name}"
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    command=self._make_theme_callback(theme_name),
                    help=f"Switch to {theme_name} theme",
                )

    def _make_command_callback(self, cmd: str) -> Any:
        """Return a callable that submits the slash command."""
        async def _run() -> None:
            app = self.app
            if isinstance(app, AgentTUI):
                app._submit_slash_command(cmd)
        return _run

    def _make_theme_callback(self, theme_name: str) -> Any:
        """Return a callable that switches the theme."""
        async def _run() -> None:
            self.app.theme = theme_name
        return _run


class AgentTUI(App[None]):
    """Main Textual application for the micro-x agent."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-area {
        height: 1fr;
    }

    #session-sidebar {
        width: 28;
        border-right: solid $primary;
        display: none;
    }

    #chat-log {
        width: 1fr;
    }

    #tool-panel {
        width: 30;
        border-left: solid $primary;
    }

    .tool-panel-title, .task-panel-title {
        text-style: bold;
        padding: 0 1;
        color: $text-muted;
    }

    .user-message {
        margin: 1 1 0 1;
        color: $text;
    }

    .assistant-message {
        margin: 0 1 0 3;
    }

    .thinking-spinner {
        margin: 0 1 0 1;
    }

    .tool-inline {
        margin: 0 1 0 3;
    }

    .system-message {
        margin: 0 1 0 1;
    }

    .error-message {
        margin: 0 1 0 1;
    }

    #log-panel {
        height: 12;
        border-top: solid $primary;
        display: none;
    }

    .log-entry {
        height: auto;
        padding: 0 1;
    }

    #prompt-input {
        margin: 0 1;
        height: 3;
    }

    #status-bar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
    }

    #keyhints {
        height: 1;
        background: $surface;
        color: yellow;
        padding: 0 1;
    }

    """

    TITLE = "MICRO-X AGENT"

    # 5.1: Register the slash command provider for the command palette
    COMMANDS = {SlashCommandProvider}

    BINDINGS = [
        Binding("escape", "cancel_task", "Cancel", show=False),
        Binding("ctrl+s", "toggle_sessions", "Sessions", show=False),
        Binding("ctrl+t", "toggle_tools", "Tools", show=False),
        Binding("ctrl+k", "toggle_tasks", "Tasks", show=False),
        Binding("ctrl+l", "toggle_logs", "Logs", show=False),
        Binding("ctrl+p", "command_palette", "Commands", show=False),
        Binding("ctrl+d", "toggle_dark", "Theme", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        app_config: AppConfig,
        runtime: AppRuntime,
        config_source: str,
    ) -> None:
        super().__init__()
        self._app_config = app_config
        self._runtime = runtime
        self._config_source = config_source
        self._agent = runtime.agent
        self._channel = TextualChannel(self)
        self._running_task: asyncio.Task[None] | None = None

        # Inject our channel into the agent and all components that captured
        # a reference to the original channel's methods at construction time.
        self._agent._channel = self._channel
        self._agent._turn_engine._channel = self._channel
        self._agent._command_handler._print = self._channel.emit_system_message

        # Subscribe to task mutations to update the TaskPanel
        if self._agent._task_manager is not None:
            self._agent._task_manager.register_mutation_listener(self._on_task_mutation)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            yield SessionSidebar(id="session-sidebar")
            yield ChatLog(id="chat-log")
            yield TaskPanel(id="task-panel")
            yield ToolPanel(id="tool-panel")
        yield LogPanel(id="log-panel")
        yield Input(placeholder="Type a message... (Enter to send, Ctrl+P for commands)", id="prompt-input")
        yield StatusBar(
            self._agent.session_accumulator,
            budget_usd=self._app_config.session_budget_usd,
            id="status-bar",
        )
        yield Static(
            "Esc:Cancel  Ctrl+S:Sessions  Ctrl+T:Tools  Ctrl+K:Tasks  "
            "Ctrl+L:Logs  Ctrl+P:Commands  Ctrl+D:Theme  Ctrl+C:Quit",
            id="keyhints",
        )

    def on_mount(self) -> None:
        """Show startup info and focus input."""
        self.title = "MICRO-X AGENT"
        model_label = f"{self._app_config.provider_name}:{self._app_config.model}"
        self.sub_title = model_label

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_system_message(f"Config: {self._config_source}")
        chat_log.add_system_message(
            f"[{model_label}] (type 'exit' to quit, Ctrl+P for command palette)"
        )
        if self._app_config.memory_enabled and self._agent.active_session_id:
            chat_log.add_system_message(
                f"Memory: enabled (session: {self._agent.active_session_id})"
            )
        if self._runtime.mcp_tools:
            chat_log.add_system_message(
                f"Tools: {len(self._runtime.mcp_tools)} MCP tools loaded"
            )
        # Load existing conversation history and costs if resuming a session
        if self._app_config.memory_enabled and self._agent.active_session_id:
            history = self._agent._memory.load_messages(self._agent.active_session_id)
            if history:
                chat_log.load_history(history)
                chat_log.add_system_message(f"--- {len(history)} messages loaded ---")
            self._restore_session_costs(self._agent.active_session_id)
            self._restore_session_tools(self._agent.active_session_id)
        chat_log.add_system_message("")

        # Wire loguru to the log panel
        from loguru import logger

        log_panel = self.query_one("#log-panel", LogPanel)
        logger.add(log_panel.sink, level="INFO", format="{message}")

        self.query_one("#status-bar", StatusBar).refresh_metrics()
        self.query_one("#prompt-input", Input).focus()

    # -- Input handling --

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user message submission via Enter."""
        text = event.value.strip()
        if not text:
            return

        # Clear input immediately
        event.input.value = ""

        if text.lower() in ("exit", "quit"):
            self.exit()
            return

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_user_message(text)

        # Disable input while agent is running
        prompt_input = self.query_one("#prompt-input", Input)
        prompt_input.disabled = True

        self._running_task = asyncio.create_task(self._run_agent(text))

    def _submit_slash_command(self, cmd: str) -> None:
        """Submit a slash command from the command palette."""
        # TUI-local commands handled without sending to agent
        if cmd.strip() == "/tasks":
            self.action_toggle_tasks()
            return

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_user_message(cmd)

        prompt_input = self.query_one("#prompt-input", Input)
        prompt_input.disabled = True

        self._running_task = asyncio.create_task(self._run_agent(cmd))

    def action_cancel_task(self) -> None:
        """Handle Escape — cancel the running agent task."""
        if self._running_task is not None and not self._running_task.done():
            self._running_task.cancel()
            chat_log = self.query_one("#chat-log", ChatLog)
            chat_log.add_system_message("[Interrupted]")

    def action_toggle_sessions(self) -> None:
        """Toggle the session sidebar visibility."""
        sidebar = self.query_one("#session-sidebar", SessionSidebar)
        sidebar.display = not sidebar.display
        if sidebar.display:
            self._refresh_session_sidebar()

    def action_toggle_tools(self) -> None:
        """Toggle the tool panel visibility."""
        tool_panel = self.query_one("#tool-panel", ToolPanel)
        tool_panel.display = not tool_panel.display

    def action_toggle_tasks(self) -> None:
        """Toggle the task panel visibility."""
        task_panel = self.query_one("#task-panel", TaskPanel)
        task_panel.set_visible(not task_panel.display)

    def _refresh_task_panel(self) -> None:
        """Refresh the TaskPanel with current tasks for the active session."""
        if self._agent._task_manager is None:
            return
        tasks = self._agent._task_manager._store.list_tasks(
            self._agent._task_manager._list_id,
        )
        try:
            task_panel = self.query_one("#task-panel", TaskPanel)
            task_panel.update_tasks(tasks)
        except Exception:
            pass  # Panel not mounted yet or app shutting down

    def _on_task_mutation(self) -> None:
        """Called by TaskManager after any task mutation — refresh the TaskPanel.

        The agent runs as an ``asyncio.create_task`` on the same event loop as
        the Textual app (see TextualChannel), so we call ``update_tasks``
        directly — ``call_from_thread`` is for different OS threads and would
        silently fail here.
        """
        self._refresh_task_panel()

    def action_toggle_logs(self) -> None:
        """Toggle the log panel visibility."""
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.display = not log_panel.display

    # 5.2: Responsive layout — hide sidebars on narrow terminals
    def on_resize(self, event: object) -> None:
        """Auto-hide sidebars when terminal is narrow."""
        width = self.size.width
        tool_panel = self.query_one("#tool-panel", ToolPanel)
        sidebar = self.query_one("#session-sidebar", SessionSidebar)
        if width < 80:
            tool_panel.display = False
            sidebar.display = False

    # 5.4: Theme toggle
    def action_toggle_dark(self) -> None:
        """Toggle between dark and light theme."""
        self.theme = "textual-light" if self.theme == "textual-dark" else "textual-dark"

    # -- Session sidebar events --

    def _restore_session_costs(self, session_id: str) -> None:
        """Restore the session accumulator from persisted metric events."""
        import json as _json

        store = getattr(self._agent._memory, "store", None)
        if store is None:
            return

        rows = store.execute(
            """
            SELECT type, payload_json
            FROM events
            WHERE session_id = ?
              AND type IN ('metric.api_call', 'metric.compaction', 'metric.tool_execution')
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

        if not rows:
            return

        events = []
        for row in rows:
            try:
                payload = _json.loads(row["payload_json"])
            except Exception:
                continue
            events.append({"type": row["type"], "payload": payload})

        self._agent._session_accumulator.restore_from_events(events)

    def _restore_session_tools(self, session_id: str) -> None:
        """Restore the tool panel from persisted tool_calls."""
        store = getattr(self._agent._memory, "store", None)
        if store is None:
            return

        rows = store.execute(
            """
            SELECT tool_name, is_error, created_at
            FROM tool_calls
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

        if not rows:
            return

        tool_calls = [dict(row) for row in rows]
        self.query_one("#tool-panel", ToolPanel).load_history(tool_calls)

    def _refresh_session_sidebar(self) -> None:
        """Refresh the session sidebar from the memory store."""
        sidebar = self.query_one("#session-sidebar", SessionSidebar)
        sm = getattr(self._agent, "_memory", None)
        session_manager = getattr(sm, "session_manager", None) if sm else None
        sidebar.refresh_sessions(session_manager, self._agent.active_session_id)

    def on_session_sidebar_session_selected(self, event: SessionSidebar.SessionSelected) -> None:
        """Handle click-to-switch session."""
        sid = event.session_id
        if sid == self._agent.active_session_id:
            return

        memory = self._agent._memory
        sm = memory.session_manager
        if sm is None:
            return

        session = sm.resolve_session_identifier(sid)
        if session is None:
            return

        resolved_id = session["id"]
        memory.active_session_id = resolved_id
        new_messages = memory.load_messages(resolved_id)
        self._agent._on_session_reset(resolved_id, new_messages)
        self._restore_session_costs(resolved_id)
        self._restore_session_tools(resolved_id)
        self._refresh_task_panel()

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.load_history(new_messages)
        chat_log.add_system_message(
            f"--- Resumed: {session.get('title', resolved_id)} ({len(new_messages)} messages) ---"
        )
        self._refresh_session_sidebar()
        self.query_one("#status-bar", StatusBar).refresh_metrics()

    def on_session_sidebar_new_session_requested(self, event: SessionSidebar.NewSessionRequested) -> None:
        """Handle New session button."""
        memory = self._agent._memory
        sm = memory.session_manager
        if sm is None:
            return

        new_id = sm.create_session()
        memory.active_session_id = new_id
        self._agent._on_session_reset(new_id, [])
        self._refresh_task_panel()

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.load_history([])  # Clear chat log
        self.query_one("#tool-panel", ToolPanel).clear_entries()
        session = sm.get_session(new_id)
        title = session.get("title", new_id) if session else new_id
        chat_log.add_system_message(f"--- New session: {title} ---")
        self._refresh_session_sidebar()
        self.query_one("#status-bar", StatusBar).refresh_metrics()

    def on_session_sidebar_fork_session_requested(self, event: SessionSidebar.ForkSessionRequested) -> None:
        """Handle Fork session button."""
        memory = self._agent._memory
        sm = memory.session_manager
        if sm is None or self._agent.active_session_id is None:
            return

        source_id = self._agent.active_session_id
        fork_id = sm.fork_session(source_id)
        memory.active_session_id = fork_id
        fork_messages = memory.load_messages(fork_id)
        self._agent._on_session_reset(fork_id, fork_messages)
        self._refresh_task_panel()

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.load_history(fork_messages)
        self._restore_session_tools(fork_id)
        chat_log.add_system_message(f"--- Forked: {source_id[:8]} -> {fork_id[:8]} ({len(fork_messages)} messages) ---")
        self._refresh_session_sidebar()
        self.query_one("#status-bar", StatusBar).refresh_metrics()

    async def _run_agent(self, text: str) -> None:
        """Run the agent in the background and re-enable input when done."""
        try:
            await self._agent.run(text)
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            chat_log = self.query_one("#chat-log", ChatLog)
            chat_log.add_error_message(str(ex))
        finally:
            prompt_input = self.query_one("#prompt-input", Input)
            prompt_input.disabled = False
            prompt_input.focus()
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.refresh_metrics()

    # -- TextualChannel callbacks (called from same event loop) --

    def on_begin_streaming(self) -> None:
        self.query_one("#chat-log", ChatLog).begin_assistant_message()

    def on_end_streaming(self) -> None:
        self.query_one("#chat-log", ChatLog).finalize_assistant_message()

    def on_text_delta(self, text: str) -> None:
        self.query_one("#chat-log", ChatLog).append_text(text)

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        self.query_one("#chat-log", ChatLog).add_tool_message(tool_name, "Running")
        self.query_one("#tool-panel", ToolPanel).tool_started(tool_use_id, tool_name)

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        status = "Error" if is_error else "Done"
        self.query_one("#chat-log", ChatLog).add_tool_message(tool_name, status)
        self.query_one("#tool-panel", ToolPanel).tool_completed(tool_use_id, tool_name, is_error)

    def on_turn_complete(self, usage: dict[str, Any]) -> None:
        self.query_one("#status-bar", StatusBar).refresh_metrics()

    def on_agent_error(self, message: str) -> None:
        self.query_one("#chat-log", ChatLog).add_error_message(message)
        # 5.5: Toast notification for errors
        self.notify(message, title="Error", severity="error", timeout=5)

    def on_system_message(self, text: str) -> None:
        self.query_one("#chat-log", ChatLog).add_system_message(text)
        # 5.5: Toast for budget warnings
        if "[Budget]" in text:
            self.notify(text, title="Budget Warning", severity="warning", timeout=8)

    def on_ask_user(
        self,
        question: str,
        options: list[dict[str, str]] | None,
        future: asyncio.Future[str],
    ) -> None:
        """Handle ask_user — push a modal dialog and resolve the future with the answer."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_system_message(f"Question: {question}")

        def _on_dismiss(answer: str | None) -> None:
            if not future.done():
                future.set_result(answer if answer else _NO_RESPONSE_MSG)

        self.push_screen(AskUserModal(question, options), callback=_on_dismiss)

    # 5.3: Mode analysis — called from agent when mode signals are detected
    def on_mode_choice(
        self,
        signals: list[str],
        recommended: str,
        reasoning: str,
        future: asyncio.Future[str],
    ) -> None:
        """Show a modal for PROMPT/COMPILED mode selection."""
        from micro_x_agent_loop.tui.screens.mode_choice_modal import ModeChoiceModal

        def _on_dismiss(answer: str | None) -> None:
            if not future.done():
                future.set_result(answer if answer else recommended)

        self.push_screen(
            ModeChoiceModal(signals, recommended, reasoning),
            callback=_on_dismiss,
        )

    # -- Shutdown --

    async def action_quit(self) -> None:
        """Clean shutdown."""
        if self._running_task is not None and not self._running_task.done():
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
        await _shutdown_runtime(self._runtime)
        self.exit()


async def _shutdown_runtime(runtime: AppRuntime) -> None:
    """Clean up all runtime resources."""
    prev_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        await runtime.agent.shutdown()
        if runtime.mcp_manager:
            await runtime.mcp_manager.close()
        if runtime.event_sink:
            await runtime.event_sink.close()
        if runtime.memory_store:
            runtime.memory_store.close()
    finally:
        signal.signal(signal.SIGINT, prev_handler)


def _install_prompt_toolkit_shutdown_hook() -> None:
    """Suppress prompt_toolkit Win32 shutdown errors.

    ``questionary`` (a dependency) imports ``prompt_toolkit`` which installs
    Win32 console input handlers.  When Textual shuts down the event loop,
    prompt_toolkit's cleanup tries to schedule futures on the closed executor
    and raises ``RuntimeError('cannot schedule new futures after shutdown')``.
    This is harmless — suppress it.
    """
    import sys

    _default_hook = sys.unraisablehook

    def _hook(unraisable: Any) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, RuntimeError) and "cannot schedule new futures" in str(exc):
            return
        _default_hook(unraisable)

    sys.unraisablehook = _hook


async def run_tui(
    app_config: AppConfig,
    runtime: AppRuntime,
    config_source: str,
) -> None:
    """Entry point — create and run the Textual TUI."""
    _install_prompt_toolkit_shutdown_hook()
    tui = AgentTUI(app_config, runtime, config_source)
    await tui.run_async()
