import asyncio
import sys

from dotenv import load_dotenv
from loguru import logger

from micro_x_agent_loop.app_config import load_json_config, parse_app_config, resolve_runtime_env
from micro_x_agent_loop.bootstrap import bootstrap_runtime


async def main() -> None:
    load_dotenv()

    raw_config = load_json_config()
    app = parse_app_config(raw_config)
    env = resolve_runtime_env(app.provider_name)
    if not env.provider_api_key:
        logger.error(f"{env.provider_env_var} environment variable is required.")
        sys.exit(1)

    try:
        runtime = await bootstrap_runtime(app, env)
    except ValueError as ex:
        logger.error(str(ex))
        sys.exit(1)

    agent = runtime.agent
    await agent.initialize_session()

    print(f"micro-x-agent-loop [{app.provider_name}:{app.model}] (type 'exit' to quit, '/help' for commands)")
    print("Tools:")
    for t in runtime.builtin_tools:
        print(f"  - {t.name}")
    if runtime.mcp_tools:
        mcp_names: dict[str, list[str]] = {}
        for t in runtime.mcp_tools:
            server, _, tool_name = t.name.partition("__")
            mcp_names.setdefault(server, []).append(tool_name or t.name)
        print("MCP servers:")
        for server, tool_names in mcp_names.items():
            print(f"  - {server}: {', '.join(tool_names)}")
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

    try:
        while True:
            try:
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
                await agent.run(trimmed)
                print("\n")
            except Exception as ex:
                logger.error(f"Unhandled error: {ex}")
    finally:
        await agent.shutdown()
        if runtime.mcp_manager:
            await runtime.mcp_manager.close()
        if runtime.event_sink:
            await runtime.event_sink.close()
        if runtime.memory_store:
            runtime.memory_store.close()


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
    asyncio.run(main())
