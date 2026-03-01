"""Template console app — copy and adapt for any AI-powered task.

Loads config from the same config files as the main agent, connects all
configured MCP servers in parallel, discovers available tools, then runs
a placeholder task you replace with your own logic.

Usage:
    python -m tools.template
    python -m tools.template --config path/to/config.json
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .mcp_client import McpClient

# ---------------------------------------------------------------------------
# Config loading (self-contained copy from app_config.py for portability)
# ---------------------------------------------------------------------------


def load_json_config(config_path: str | None = None) -> tuple[dict, str]:
    """Load application config, supporting file indirection and CLI override.

    Resolution order:
    1. config_path argument (from --config CLI flag) — load directly
    2. ConfigFile field inside ./config.json — resolve relative to CWD
    3. ./config.json itself (backward compatible)

    Returns:
        (config_dict, resolved_path) tuple.
    """
    if config_path:
        p = Path(config_path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        with open(p) as f:
            return json.load(f), str(p)

    default_path = Path.cwd() / "config.json"
    if not default_path.exists():
        return {}, "config.json (defaults)"

    with open(default_path) as f:
        data = json.load(f)

    config_file = data.get("ConfigFile")
    if config_file:
        target = Path.cwd() / config_file
        if not target.exists():
            raise FileNotFoundError(
                f"ConfigFile target not found: {target} "
                f"(referenced from config.json)"
            )
        with open(target) as f:
            return json.load(f), str(config_file)

    return data, "config.json"


# ---------------------------------------------------------------------------
# MCP connection
# ---------------------------------------------------------------------------


async def connect_all_mcp_servers(
    server_configs: dict[str, dict[str, Any]],
) -> dict[str, McpClient]:
    """Connect to all configured MCP servers in parallel.

    Launches all servers concurrently, then awaits each. Servers that fail
    to connect are skipped with a warning (the rest still work).

    Returns:
        Dict mapping server name to connected McpClient.
    """
    # Launch all connection tasks
    clients: dict[str, McpClient] = {}
    tasks: dict[str, asyncio.Task] = {}

    for name, cfg in server_configs.items():
        command = cfg.get("command", "")
        args = cfg.get("args", [])
        env = cfg.get("env")
        if not command:
            print(f"  WARNING: Server '{name}' has no command, skipping")
            continue

        client = McpClient(name)
        clients[name] = client
        tasks[name] = asyncio.create_task(client.connect(command, args, env))

    # Await all — collect successes, skip failures
    connected: dict[str, McpClient] = {}
    for name, task in tasks.items():
        try:
            await task
            connected[name] = clients[name]
            print(f"  {name}: connected")
        except Exception as ex:
            print(f"  {name}: FAILED ({ex})")

    return connected


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------


async def discover_tools(
    clients: dict[str, McpClient],
) -> dict[str, list[tuple[str, str]]]:
    """Discover tools from all connected servers.

    Returns:
        Dict mapping server name to list of (tool_name, description) tuples.
    """
    catalog: dict[str, list[tuple[str, str]]] = {}
    for name, client in clients.items():
        try:
            catalog[name] = await client.list_tools()
        except Exception as ex:
            print(f"  WARNING: Failed to list tools for '{name}': {ex}")
            catalog[name] = []
    return catalog


def print_tool_catalog(catalog: dict[str, list[tuple[str, str]]]) -> None:
    """Print a formatted listing of all discovered tools by server."""
    total = sum(len(tools) for tools in catalog.values())
    print(f"\nTool catalog ({total} tools across {len(catalog)} servers):")
    print("-" * 60)
    for server_name, tools in sorted(catalog.items()):
        print(f"\n  [{server_name}] ({len(tools)} tools)")
        for tool_name, description in tools:
            desc_short = description[:70] + "..." if len(description) > 70 else description
            print(f"    {tool_name:30s}  {desc_short}")


# ---------------------------------------------------------------------------
# Task placeholder — REPLACE THIS with your own logic
# ---------------------------------------------------------------------------


async def run_task(
    clients: dict[str, McpClient],
    catalog: dict[str, list[tuple[str, str]]],
    config: dict,
) -> None:
    """Placeholder task — replace with your own orchestration logic.

    This function has access to:
    - clients: Connected MCP servers for calling tools
    - catalog: Tool names/descriptions for building prompts
    - config: Full config dict for reading settings

    Example — calling an MCP tool:
        result = await clients["google"].call_tool("gmail_search", {
            "query": "from:alerts@example.com",
            "maxResults": 10,
        })
        # result is a dict (structuredContent) or string (text fallback)

    Example — calling the LLM (non-streaming):
        from .llm import create_message, estimate_cost
        text, usage = await create_message(
            model=config.get("Model", "claude-haiku-4-5-20251001"),
            max_tokens=4096,
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(f"Cost: ${estimate_cost(usage):.4f}")

    Example — calling the LLM (streaming):
        from .llm import stream_message, estimate_cost
        text, usage = await stream_message(
            model=config.get("Model", "claude-sonnet-4-5-20250929"),
            max_tokens=8192,
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Write something..."}],
        )
        print(f"\\nCost: ${estimate_cost(usage):.4f}")
    """
    print("\n[Task placeholder]")
    print("Edit run_task() in __main__.py to implement your task.")
    print(f"Available: {len(clients)} MCP servers, "
          f"{sum(len(t) for t in catalog.values())} tools, "
          f"model={config.get('Model', 'not set')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    load_dotenv()

    # Parse --config flag
    config_path = None
    args = sys.argv[1:]
    if "--config" in args:
        idx = args.index("--config")
        if idx + 1 < len(args):
            config_path = args[idx + 1]

    # Load config
    config, source = load_json_config(config_path)
    print(f"Config: {source}")
    print(f"Model: {config.get('Model', 'not configured')}")

    # Connect all MCP servers
    mcp_configs = config.get("McpServers", {})
    if not mcp_configs:
        print("\nNo MCP servers configured.")
        clients: dict[str, McpClient] = {}
    else:
        print(f"\nConnecting {len(mcp_configs)} MCP servers...")
        clients = await connect_all_mcp_servers(mcp_configs)
        print(f"\n{len(clients)}/{len(mcp_configs)} servers connected")

    try:
        # Discover tools
        catalog = await discover_tools(clients)
        print_tool_catalog(catalog)

        # Run the task
        await run_task(clients, catalog, config)

    finally:
        # Clean shutdown
        if clients:
            print("\nShutting down MCP servers...")
            for name, client in clients.items():
                try:
                    await client.close()
                except Exception:
                    pass
            print("Done.")


def _run() -> None:
    """Windows-safe entry point that suppresses pipe-close noise on shutdown."""
    # Suppress "unclosed transport" noise from asyncio subprocess cleanup on Windows.
    # These come from __del__ methods on already-closed pipes and are harmless.
    _original_hook = sys.unraisablehook

    def _quiet_hook(args) -> None:
        if args.exc_type is ValueError and "closed pipe" in str(args.exc_value):
            return
        if args.exc_type is ResourceWarning and "unclosed transport" in str(args.exc_value):
            return
        _original_hook(args)

    sys.unraisablehook = _quiet_hook
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    _run()
