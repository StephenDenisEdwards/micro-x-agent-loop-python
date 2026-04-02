"""CLI dispatch — routes parsed arguments to the appropriate handler."""

from __future__ import annotations

import os
import sys
from typing import Any

from loguru import logger

from micro_x_agent_loop.app_config import parse_app_config, resolve_runtime_env
from micro_x_agent_loop.bootstrap import bootstrap_runtime
from micro_x_agent_loop.cli.repl import run_repl, shutdown_runtime


async def run_oneshot(
    app: Any,
    env: Any,
    prompt: str,
    session_id: str | None,
    *,
    resolved_config: dict[str, Any],
) -> None:
    """Execute a single prompt in autonomous mode and exit."""
    if session_id:
        app.resume_session_id = session_id

    try:
        runtime = await bootstrap_runtime(app, env, autonomous=True, resolved_config=resolved_config)
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
        await shutdown_runtime(runtime)


async def dispatch(cli_args: dict, raw_config: dict, config_source: str) -> None:
    """Route CLI arguments to the correct handler."""
    # Job commands — no agent bootstrap needed.
    if cli_args["job"] is not None:
        from micro_x_agent_loop.broker.cli import handle_job_command

        await handle_job_command(cli_args["job"], config=raw_config)
        return

    # Broker start → server with broker enabled.
    if cli_args["broker"] is not None:
        broker_args = cli_args["broker"]
        if not broker_args or broker_args[0] == "start":
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

    # Server: start or connect as client.
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

    # From here on, we need full agent bootstrap.
    app = parse_app_config(raw_config)

    pricing_overrides = raw_config.get("Pricing", {})
    if pricing_overrides:
        from micro_x_agent_loop.usage import load_pricing_overrides

        load_pricing_overrides(pricing_overrides)

    env = resolve_runtime_env(app.provider_name)
    if not env.provider_api_key:
        logger.error(f"{env.provider_env_var} environment variable is required.")
        sys.exit(1)

    # One-shot mode.
    if cli_args["run"]:
        await run_oneshot(
            app, env, cli_args["run"], cli_args["session"],
            resolved_config=raw_config,
        )
        return

    # Textual TUI mode.
    if cli_args.get("tui"):
        try:
            from micro_x_agent_loop.tui.app import run_tui
        except ImportError:
            print("Textual is not installed. Install with: pip install -e \".[tui]\"")
            sys.exit(1)

        # Suppress log output to stderr — Textual owns the terminal
        import logging as _logging

        _logging.disable(_logging.CRITICAL)
        logger.remove()
        logger.add(os.path.join(".micro_x", "tui.log"), level="DEBUG", rotation="5 MB")

        try:
            runtime = await bootstrap_runtime(app, env, resolved_config=raw_config)
        except ValueError as ex:
            logger.error(str(ex))
            sys.exit(1)

        agent = runtime.agent
        await agent.initialize_session()

        await run_tui(app, runtime, config_source)
        return

    # Interactive REPL.
    try:
        runtime = await bootstrap_runtime(app, env, resolved_config=raw_config)
    except ValueError as ex:
        logger.error(str(ex))
        sys.exit(1)

    agent = runtime.agent
    await agent.initialize_session()

    await run_repl(app, runtime, config_source)
