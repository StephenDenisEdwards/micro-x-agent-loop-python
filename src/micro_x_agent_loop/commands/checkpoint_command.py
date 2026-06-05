"""`/rewind` and `/checkpoint` — file-checkpoint rewind / listing commands."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_rewind(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    cm = ctx.memory.checkpoint_manager
    if not ctx.memory_enabled or cm is None:
        ctx.print(f"{p}Rewind requires MemoryEnabled=true")
        return
    parts = command.split()
    if len(parts) != 2:
        ctx.print(f"{p}Usage: /rewind <checkpoint_id>")
        return

    checkpoint_id = parts[1]
    try:
        _, outcomes = cm.rewind_files(checkpoint_id)
    except Exception as ex:
        ctx.print(f"{p}Rewind failed: {ex}")
        return

    for line in ctx.checkpoint_service.format_rewind_outcome_lines(checkpoint_id, outcomes):
        ctx.print(line)


async def handle_checkpoint(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    cm = ctx.memory.checkpoint_manager
    active_id = ctx.memory.active_session_id
    if not ctx.memory_enabled or cm is None or active_id is None:
        ctx.print(f"{p}Checkpoint commands require MemoryEnabled=true")
        return

    parts = command.split()
    if len(parts) == 1 or (len(parts) >= 2 and parts[1] == "list"):
        limit = 20
        if len(parts) >= 3:
            try:
                limit = int(parts[2])
            except ValueError:
                ctx.print(f"{p}Usage: /checkpoint list [limit]")
                return
        checkpoints = cm.list_checkpoints(active_id, limit=limit)
        if not checkpoints:
            ctx.print(f"{p}No checkpoints found for current session.")
            return
        ctx.print(f"{p}Recent checkpoints:")
        for cp in checkpoints:
            ctx.print(ctx.checkpoint_service.format_checkpoint_list_entry(cp))
        return

    if len(parts) == 3 and parts[1] == "rewind":
        await handle_rewind(ctx, f"/rewind {parts[2]}")
        return

    ctx.print(f"{p}Usage: /checkpoint list [limit] | /checkpoint rewind <checkpoint_id>")
