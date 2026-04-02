from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from dotenv import load_dotenv
from loguru import logger

from micro_x_agent_loop.app_config import load_json_config
from micro_x_agent_loop.cli.dispatch import dispatch
from micro_x_agent_loop.cli.esc_watcher import EscWatcher as _EscWatcher  # noqa: F401
from micro_x_agent_loop.cli.repl import (  # noqa: F401
    create_prompt_session as _create_prompt_session,
)


def _parse_cli_args() -> dict:
    """Parse CLI arguments (simple, no argparse).

    Supported flags:
        --config <path>         Config file path
        --run <prompt>          One-shot execution (autonomous mode)
        --session <id>          Session ID for --run
        --broker <subcommand>   Broker daemon management (start/stop/status)
        --job <subcommand> ...  Job management (add/list/remove/enable/disable/run-now/runs)
        --server <subcommand>   API server management (start)
        --tui                   Launch Textual TUI (requires: pip install -e ".[tui]")
    """
    args: dict = {
        "config": None,
        "run": None,
        "session": None,
        "broker": None,
        "job": None,
        "server": None,
        "tui": False,
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
            args["broker"] = argv[i + 1 :]
            break
        elif argv[i] == "--job":
            args["job"] = argv[i + 1 :]
            break
        elif argv[i] == "--server":
            args["server"] = argv[i + 1 :]
            break
        elif argv[i] == "--tui":
            args["tui"] = True
            i += 1
        else:
            i += 1
    return args


class _McpNotificationFilter(logging.Filter):
    """Suppress noisy MCP SDK notification validation warnings."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.WARNING and "Failed to validate notification" in str(record.msg):
            return False
        return True


def _print_startup_banner() -> None:
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
    )
    print("By Stephen Edwards")
    print()


async def main() -> None:
    load_dotenv()
    logger.remove()
    logging.getLogger().addFilter(_McpNotificationFilter())

    cli_args = _parse_cli_args()

    if not cli_args["run"] and not cli_args.get("tui"):
        _print_startup_banner()

    raw_config, config_source = load_json_config(config_path=cli_args["config"])
    await dispatch(cli_args, raw_config, config_source)


def _install_transport_cleanup_hook() -> None:
    """Suppress 'unclosed transport' noise from asyncio subprocess cleanup on Windows."""
    _default_hook = sys.unraisablehook

    def _hook(unraisable: Any) -> None:
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
