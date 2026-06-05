"""`/tools mcp` — list available MCP servers and their tools."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_tools(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    parts = command.split()
    if len(parts) == 2 and parts[1] == "mcp":
        _print_mcp_tools(ctx)
        return
    ctx.print(f"{p}Usage: /tools mcp")


def _print_mcp_tools(ctx: CommandContext) -> None:
    p = ctx.line_prefix
    groups: dict[str, list[str]] = {}
    for name in ctx.tool_map:
        if "__" not in name:
            continue
        server, short = name.split("__", 1)
        groups.setdefault(server, []).append(short)
    if not groups:
        ctx.print(f"{p}No MCP tools loaded.")
        return
    ctx.print(f"{p}MCP servers:")
    for server in sorted(groups):
        ctx.print(f"{p}  {server}:")
        for short in sorted(groups[server]):
            ctx.print(f"{p}    - {short}")
