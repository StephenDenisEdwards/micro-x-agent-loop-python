"""`/replay [session_id] [--full]` — render a turn-by-turn step-through of a session."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_replay(ctx: CommandContext, command: str) -> None:
    from micro_x_agent_loop.session_replay import reconstruct_session

    p = ctx.line_prefix
    store = ctx.memory.store
    if not ctx.memory_enabled or store is None:
        ctx.print(f"{p}Replay requires MemoryEnabled=true")
        return

    parts = command.split()
    flags = {q for q in parts[1:] if q.startswith("-")}
    full = "--full" in flags or "--verbatim" in flags
    positional = [q for q in parts[1:] if not q.startswith("-")]
    session_id = positional[0] if positional else ctx.memory.active_session_id
    if not session_id:
        ctx.print(f"{p}Usage: /replay [session_id] [--full]  (no active session)")
        return

    try:
        lines = reconstruct_session(store, session_id, full=full)
    except ValueError as ex:
        ctx.print(f"{p}{ex}")
        return
    for line in lines:
        ctx.print(f"{p}{line}")
