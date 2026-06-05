"""`/compact [tail N]` — force conversation compaction now."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_compact(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    if ctx.on_force_compact is None:
        ctx.print(f"{p}Compaction not available (strategy is 'none').")
        return

    parts = command.split()
    protected_tail: int | None = None
    if len(parts) >= 3 and parts[1] == "tail":
        try:
            protected_tail = int(parts[2])
        except ValueError:
            ctx.print(f"{p}Usage: /compact [tail N]")
            return
    elif len(parts) > 1:
        ctx.print(f"{p}Usage: /compact [tail N]")
        return

    ok, message = await ctx.on_force_compact(protected_tail)
    ctx.print(f"{p}{message}")
