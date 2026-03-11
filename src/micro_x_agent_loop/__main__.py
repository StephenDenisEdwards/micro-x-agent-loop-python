from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

from dotenv import load_dotenv
from loguru import logger

from micro_x_agent_loop.app_config import load_json_config, parse_app_config, resolve_runtime_env
from micro_x_agent_loop.bootstrap import bootstrap_runtime


class _EscWatcher:
    """Watches for ESC keypress in a background thread to cancel an asyncio task.

    Uses Windows Console API (ReadConsoleInput) to read keyboard events directly,
    avoiding conflicts with Python's input() which uses a separate read path.
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._available = False
        try:
            import ctypes
            self._kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            self._available = True
        except (ImportError, AttributeError, OSError):
            pass

    def start(self, task: asyncio.Task, loop: asyncio.AbstractEventLoop) -> None:
        if not self._available:
            return
        self._task = task
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._task = None
        self._loop = None

    def shutdown(self) -> None:
        self.stop()

    def _poll(self) -> None:
        import ctypes
        import ctypes.wintypes as wt

        STD_INPUT_HANDLE = -10
        KEY_EVENT = 0x0001
        VK_ESCAPE = 0x1B

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("bKeyDown", wt.BOOL),
                ("wRepeatCount", wt.WORD),
                ("wVirtualKeyCode", wt.WORD),
                ("wVirtualScanCode", wt.WORD),
                ("uChar", wt.WCHAR),
                ("dwControlKeyState", wt.DWORD),
            ]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [
                ("EventType", wt.WORD),
                ("_padding", wt.WORD),
                ("Event", KEY_EVENT_RECORD),
            ]

        kernel32 = self._kernel32
        h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)

        rec = INPUT_RECORD()
        read_count = wt.DWORD(0)

        while not self._stop_event.is_set():
            # WaitForSingleObject with 100ms timeout so we can check _stop_event
            result = kernel32.WaitForSingleObject(h_stdin, 100)
            if result != 0:  # WAIT_OBJECT_0
                continue

            # Peek (not read) to avoid consuming events needed by questionary/input()
            avail = wt.DWORD(0)
            kernel32.GetNumberOfConsoleInputEvents(h_stdin, ctypes.byref(avail))
            if avail.value == 0:
                continue

            success = kernel32.PeekConsoleInputW(
                h_stdin, ctypes.byref(rec), 1, ctypes.byref(read_count)
            )
            if not success or read_count.value == 0:
                continue

            if (
                rec.EventType == KEY_EVENT
                and rec.Event.bKeyDown
                and rec.Event.wVirtualKeyCode == VK_ESCAPE
            ):
                # Consume only the ESC event
                kernel32.ReadConsoleInputW(
                    h_stdin, ctypes.byref(rec), 1, ctypes.byref(read_count)
                )
                task = self._task
                loop = self._loop
                if task is not None and loop is not None and not task.done():
                    loop.call_soon_threadsafe(task.cancel)
                return

            # Not ESC — flush the peeked event so we don't spin on it,
            # but only if it's not a key event (mouse, focus, etc.)
            if rec.EventType != KEY_EVENT:
                kernel32.ReadConsoleInputW(
                    h_stdin, ctypes.byref(rec), 1, ctypes.byref(read_count)
                )
            else:
                # Key event that isn't ESC — leave it for input()/questionary.
                # Sleep briefly to avoid busy-spinning while waiting for ESC.
                self._stop_event.wait(0.1)


def _parse_cli_args() -> dict:
    """Parse CLI arguments (simple, no argparse).

    Supported flags:
        --config <path>         Config file path
        --run <prompt>          One-shot execution (autonomous mode)
        --session <id>          Session ID for --run
        --broker <subcommand>   Broker daemon management (start/stop/status)
        --job <subcommand> ...  Job management (add/list/remove/enable/disable/run-now/runs)
        --server <subcommand>   API server management (start)
    """
    args: dict = {
        "config": None, "run": None, "session": None,
        "broker": None, "job": None, "server": None,
    }
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--config" and i + 1 < len(argv):
            args["config"] = argv[i + 1]
            i += 2
        elif argv[i] == "--run" and i + 1 < len(argv):
            args["run"] = argv[i + 1]
            i += 2
        elif argv[i] == "--session" and i + 1 < len(argv):
            args["session"] = argv[i + 1]
            i += 2
        elif argv[i] == "--broker":
            # Collect remaining args as broker subcommand
            args["broker"] = argv[i + 1:]
            break
        elif argv[i] == "--job":
            # Collect remaining args as job subcommand
            args["job"] = argv[i + 1:]
            break
        elif argv[i] == "--server":
            # Collect remaining args as server subcommand
            args["server"] = argv[i + 1:]
            break
        else:
            i += 1
    return args


class _McpNotificationFilter(logging.Filter):
    """Suppress noisy MCP SDK notification validation warnings.

    Some third-party MCP servers (e.g. mcp-discord) send non-standard
    notification methods like ``method='log'`` instead of the spec-compliant
    ``notifications/message``.  The Python MCP SDK logs a wall of Pydantic
    validation errors for each one.  These are harmless — the server still
    works — but they clutter startup output badly.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.WARNING and "Failed to validate notification" in str(record.msg):
            return False
        return True


async def _shutdown_runtime(runtime) -> None:
    """Clean up all runtime resources.

    On Windows, MCP server subprocess termination can send CTRL_C_EVENT to
    the console process group, which makes cmd.exe show "Terminate batch job
    (Y/N)?" if running from a .bat file.  We temporarily ignore SIGINT during
    shutdown to prevent this.
    """
    import signal
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


async def _run_oneshot(app, env, prompt: str, session_id: str | None) -> None:
    """Execute a single prompt in autonomous mode and exit."""
    if session_id:
        app.resume_session_id = session_id

    try:
        runtime = await bootstrap_runtime(app, env, autonomous=True)
    except ValueError as ex:
        logger.error(str(ex))
        sys.exit(1)

    agent = runtime.agent
    await agent.initialize_session()

    try:
        await agent.run(prompt)
    except Exception as ex:
        logger.error(f"One-shot run failed: {ex}")
        sys.exit(1)
    finally:
        await _shutdown_runtime(runtime)


async def main() -> None:
    load_dotenv()

    # Suppress MCP SDK notification validation noise from non-standard servers.
    logging.getLogger().addFilter(_McpNotificationFilter())

    cli_args = _parse_cli_args()

    # -- Startup logo (display first, skip in one-shot mode) --
    if not cli_args["run"]:
        _YELLOW = "\033[33m"
        _BLUE = "\033[34m"
        _RESET = "\033[0m"
        print(
            f"{_YELLOW}"
            "  ███╗   ███╗██╗ ██████╗██████╗  ██████╗     ██╗  ██╗\n"
            "  ████╗ ████║██║██╔════╝██╔══██╗██╔═══██╗    ╚██╗██╔╝\n"
            "  ██╔████╔██║██║██║     ██████╔╝██║   ██║█████╗╚███╔╝\n"
            "  ██║╚██╔╝██║██║██║     ██╔══██╗██║   ██║╚════╝██╔██╗\n"
            "  ██║ ╚═╝ ██║██║╚██████╗██║  ██║╚██████╔╝    ██╔╝ ██╗\n"
            "  ╚═╝     ╚═╝╚═╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝  ╚═╝\n"
            "        █████╗  ██████╗ ███████╗███╗   ██╗████████╗\n"
            "       ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝\n"
            "       ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║\n"
            "       ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║\n"
            "       ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║\n"
            "       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝"
            f"{_RESET}\n"
            f"{_BLUE}                        AI{_RESET}\n"
            f"{_RESET}              By Stephen Edwards{_RESET}\n"
        )

    raw_config, config_source = load_json_config(config_path=cli_args["config"])

    # -- Job commands: don't need full agent bootstrap --
    if cli_args["job"] is not None:
        from micro_x_agent_loop.broker.cli import handle_job_command
        await handle_job_command(cli_args["job"], config=raw_config)
        return

    # -- Broker start → alias for --server start with broker enabled --
    if cli_args["broker"] is not None:
        broker_args = cli_args["broker"]
        if not broker_args or broker_args[0] == "start":
            # Broker start now launches the unified API server with broker enabled
            from micro_x_agent_loop.server.app import run_server
            await run_server(
                config_path=cli_args["config"],
                host=os.environ.get("SERVER_HOST", raw_config.get("BrokerHost", "127.0.0.1")),
                port=int(os.environ.get("SERVER_PORT", raw_config.get("BrokerPort", "8321"))),
                api_secret=os.environ.get("SERVER_API_SECRET", raw_config.get("BrokerApiSecret")),
                max_sessions=int(os.environ.get("SERVER_MAX_SESSIONS", "10")),
                session_timeout_minutes=int(os.environ.get("SERVER_SESSION_TIMEOUT_MINUTES", "30")),
                broker_enabled=True,
            )
        else:
            from micro_x_agent_loop.broker.cli import handle_broker_command
            await handle_broker_command(broker_args, config=raw_config)
        return

    # -- Server command: start server or connect as client --
    if cli_args["server"] is not None:
        server_args = cli_args["server"]
        if not server_args or server_args[0] == "start":
            from micro_x_agent_loop.server.app import run_server
            broker_flag = "--broker" in server_args if server_args else False
            await run_server(
                config_path=cli_args["config"],
                host=os.environ.get("SERVER_HOST", "127.0.0.1"),
                port=int(os.environ.get("SERVER_PORT", "8321")),
                api_secret=os.environ.get("SERVER_API_SECRET"),
                max_sessions=int(os.environ.get("SERVER_MAX_SESSIONS", "10")),
                session_timeout_minutes=int(os.environ.get("SERVER_SESSION_TIMEOUT_MINUTES", "30")),
                broker_enabled=broker_flag or bool(os.environ.get("SERVER_BROKER_ENABLED")),
            )
        elif server_args[0].startswith("http://") or server_args[0].startswith("https://"):
            # Client mode: connect to a running server
            from micro_x_agent_loop.server.client import run_client
            await run_client(
                server_args[0],
                session_id=cli_args["session"],
                api_secret=os.environ.get("SERVER_API_SECRET"),
            )
        else:
            print(f"Unknown server command: {server_args[0]}")
            print("Usage:")
            print("  --server start [--broker]              Start the API server")
            print("  --server http://host:port [--session]  Connect to a running server")
        return

    app = parse_app_config(raw_config)
    env = resolve_runtime_env(app.provider_name)
    if not env.provider_api_key:
        logger.error(f"{env.provider_env_var} environment variable is required.")
        sys.exit(1)

    # -- One-shot mode: run prompt and exit --
    if cli_args["run"]:
        await _run_oneshot(app, env, cli_args["run"], cli_args["session"])
        return

    print(f"Config: {config_source}")

    try:
        runtime = await bootstrap_runtime(app, env)
    except ValueError as ex:
        logger.error(str(ex))
        sys.exit(1)

    agent = runtime.agent
    await agent.initialize_session()

    print(f"micro-x-agent-loop [{app.provider_name}:{app.model}] (type 'exit' to quit, '/help' for commands)")
    if runtime.mcp_tools:
        mcp_names: dict[str, list[str]] = {}
        for t in runtime.mcp_tools:
            server, _, tool_name = t.name.partition("__")
            mcp_names.setdefault(server, []).append(tool_name or t.name)
        logger.info("MCP servers:")
        for server, tool_names in mcp_names.items():
            logger.info(f"  {server}:")
            for name in tool_names:
                logger.info(f"    - {name}")
    if app.working_directory:
        print(f"Working directory: {app.working_directory}")
    if app.compaction_strategy_name != "none":
        print(
            f"Compaction: {app.compaction_strategy_name} "
            f"(threshold: {app.compaction_threshold_tokens:,} tokens, tail: {app.protected_tail_messages} messages)"
        )
    if app.memory_enabled:
        print(f"Memory: enabled (session: {agent.active_session_id})")
        print(
            "Memory controls: /session, /session list [limit], /session name <title>, "
            "/session new [title], /session resume <id-or-name>, /session fork, "
            "/checkpoint list [limit], /checkpoint rewind <checkpoint_id>"
        )
    if runtime.log_descriptions:
        print(f"Logging: {', '.join(runtime.log_descriptions)}")
    print()

    # --- ESC key listener for task interruption ---
    _esc_watcher = _EscWatcher()

    # prompt_toolkit session — Enter submits, Shift+Enter inserts newline,
    # and bracketed paste captures multi-line content in one go.
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event: KeyPressEvent) -> None:
        """Enter always submits, even when buffer has multiple lines."""
        event.current_buffer.validate_and_handle()

    @bindings.add("s-enter")
    @bindings.add("escape", "enter")
    def _newline(event: KeyPressEvent) -> None:
        """Shift+Enter or Alt+Enter inserts a newline."""
        event.current_buffer.insert_text("\n")

    session: PromptSession[str] = PromptSession(
        message=HTML("<b>you&gt; </b>"),
        multiline=True,
        key_bindings=bindings,
        prompt_continuation=".... ",
    )

    try:
        while True:
            try:
                user_input = await asyncio.to_thread(session.prompt)
            except (EOFError, KeyboardInterrupt):
                break

            trimmed = user_input.strip()
            if trimmed in ("exit", "quit"):
                break
            if not trimmed:
                continue

            try:
                print()
                task = asyncio.create_task(agent.run(trimmed))
                loop = asyncio.get_running_loop()
                _esc_watcher.start(task, loop)
                try:
                    await task
                except asyncio.CancelledError:
                    print("\nassistant> [Interrupted]")
                finally:
                    _esc_watcher.stop()
                print("\n")
            except Exception as ex:
                logger.error(f"Unhandled error: {ex}")
                print(f"\nassistant> Error: {ex}\n")
    finally:
        _esc_watcher.shutdown()
        await _shutdown_runtime(runtime)


def _install_transport_cleanup_hook() -> None:
    """Suppress 'unclosed transport' noise from asyncio subprocess cleanup on Windows.

    When MCP stdio servers shut down, asyncio's proactor transport __del__ methods
    fire after pipes are already closed, producing ugly but harmless tracebacks.
    """
    _default_hook = sys.unraisablehook

    def _hook(unraisable) -> None:
        obj_str = str(unraisable.object) if unraisable.object is not None else ""
        if "Transport" in obj_str and isinstance(unraisable.exc_value, (ResourceWarning, ValueError)):
            return
        _default_hook(unraisable)

    sys.unraisablehook = _hook


if __name__ == "__main__":
    _install_transport_cleanup_hook()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
