"""Interactive REPL loop — prompt session, status bar, ESC cancellation."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from loguru import logger

from micro_x_agent_loop.app_config import AppConfig
from micro_x_agent_loop.bootstrap import AppRuntime
from micro_x_agent_loop.cli.esc_watcher import EscWatcher


def create_prompt_session(toolbar_fn: Any = None) -> Any:
    """Build the interactive prompt_toolkit session."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    kwargs: dict = {
        "message": HTML("<b>you&gt; </b>"),
        "multiline": True,
        "key_bindings": bindings,
        "prompt_continuation": ".... ",
    }
    if toolbar_fn is not None:
        from prompt_toolkit.styles import Style

        kwargs["bottom_toolbar"] = toolbar_fn
        kwargs["style"] = Style.from_dict(
            {
                "bottom-toolbar": "bg:#333333 #aaaaaa",
            }
        )

    return PromptSession(**kwargs)


async def shutdown_runtime(runtime: AppRuntime) -> None:
    """Clean up all runtime resources.

    On Windows, MCP server subprocess termination can send CTRL_C_EVENT to
    the console process group.  We temporarily ignore SIGINT during shutdown.
    """
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


async def run_repl(
    app: AppConfig,
    runtime: AppRuntime,
    config_source: str,
) -> None:
    """Run the interactive REPL loop."""
    agent = runtime.agent

    print(f"Config: {config_source}")
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
            f"(threshold: {app.compaction_threshold_tokens:,} tokens, "
            f"tail: {app.protected_tail_messages} messages)"
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

    esc_watcher = EscWatcher()

    toolbar_fn = None
    if app.status_bar_enabled:
        accumulator = agent.session_accumulator

        def toolbar_fn() -> Any:
            from prompt_toolkit.formatted_text import HTML

            text = accumulator.format_toolbar(budget_usd=app.session_budget_usd)
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return HTML(f" <b>{text}</b>")

    session = None
    try:
        logger.info("Creating prompt_toolkit session...")
        session = await asyncio.wait_for(asyncio.to_thread(create_prompt_session, toolbar_fn), timeout=5.0)
        logger.info("PromptSession created, entering REPL loop...")
    except TimeoutError:
        logger.warning("prompt_toolkit setup timed out; falling back to basic console input")
    except Exception as ex:
        logger.warning(f"prompt_toolkit setup failed; falling back to basic console input: {ex}")

    try:
        while True:
            try:
                if session is not None:
                    logger.info("Calling session.prompt()...")
                    user_input = await asyncio.to_thread(session.prompt)
                else:
                    user_input = await asyncio.to_thread(input, "you> ")
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
                esc_watcher.start(task, loop)
                try:
                    await task
                except asyncio.CancelledError:
                    print("\nassistant> [Interrupted]")
                finally:
                    esc_watcher.stop()
                if session is None and app.status_bar_enabled:
                    toolbar_text = agent.session_accumulator.format_toolbar(budget_usd=app.session_budget_usd)
                    if toolbar_text:
                        print(f"  [{toolbar_text}]")
                print("\n")
            except Exception as ex:
                logger.error(f"Unhandled error: {ex}")
                print(f"\nassistant> Error: {ex}\n")
    finally:
        esc_watcher.shutdown()
        await shutdown_runtime(runtime)
