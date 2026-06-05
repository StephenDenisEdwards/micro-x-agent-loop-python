"""`/cost` and `/cost reconcile` — session cost summary and provider reconciliation."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_cost(ctx: CommandContext, command: str) -> None:
    parts = command.split()
    if len(parts) >= 2 and parts[1] == "reconcile":
        await _handle_cost_reconcile(ctx, parts)
        return
    ctx.print(f"{ctx.line_prefix}{ctx.session_accumulator.format_summary()}")


async def _handle_cost_reconcile(ctx: CommandContext, parts: list[str]) -> None:
    from micro_x_agent_loop.cost_reconciliation import reconcile_costs

    p = ctx.line_prefix
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
                ctx.print(f"{p}Usage: /cost reconcile [days] [--start YYYY-MM-DD] [--end YYYY-MM-DD]")
                return
            i += 1

    store = ctx.memory.store
    try:
        lines = await reconcile_costs(ctx.tool_map, store, days=days, start=start, end=end)
    except ValueError as ex:
        ctx.print(f"{p}Invalid date format: {ex}")
        ctx.print(f"{p}Use YYYY-MM-DD (e.g. 2026-03-01)")
        return
    for line in lines:
        ctx.print(f"{p}{line}")
