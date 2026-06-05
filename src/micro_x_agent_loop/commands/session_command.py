"""`/session` — session lifecycle commands (new/list/name/resume/fork)."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_session(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    sm = ctx.memory.session_manager
    if not ctx.memory_enabled or sm is None:
        ctx.print(f"{p}Session commands require MemoryEnabled=true")
        return

    parts = command.split()
    if len(parts) == 1:
        active_id = ctx.memory.active_session_id
        if active_id is None:
            ctx.print(f"{p}Current session: none")
            return
        session = sm.get_session(active_id)
        title = session.get("title", active_id) if session else active_id
        ctx.print(
            f"{p}Current session: {title} [{ctx.session_controller.short_id(active_id)}] (id={active_id})"
        )
        return

    if len(parts) >= 2 and parts[1] == "list":
        limit = 20
        if len(parts) >= 3:
            try:
                limit = int(parts[2])
            except ValueError:
                ctx.print(f"{p}Usage: /session list [limit]")
                return
        sessions = sm.list_sessions(limit=limit)
        if not sessions:
            ctx.print(f"{p}No sessions found.")
            return
        ctx.print(f"{p}Recent sessions:")
        for s in sessions:
            ctx.print(
                ctx.session_controller.format_session_list_entry(
                    s, active_session_id=ctx.memory.active_session_id
                )
            )
        return

    if len(parts) >= 2 and parts[1] == "new":
        title = command.partition("new")[2].strip()
        new_id = sm.create_session(title=title if title else None)
        ctx.memory.active_session_id = new_id
        ctx.on_session_reset(new_id, ctx.memory.load_messages(new_id))
        session = sm.get_session(new_id) or {"title": new_id}
        ctx.print(
            f"{p}Started new session: {session.get('title', new_id)} "
            f"[{ctx.session_controller.short_id(new_id)}] (id={new_id})"
        )
        return

    if len(parts) >= 3 and parts[1] == "name":
        active_id = ctx.memory.active_session_id
        if active_id is None:
            ctx.print(f"{p}No active session to name")
            return
        title = command.partition("name")[2].strip()
        if not title:
            ctx.print(f"{p}Usage: /session name <title>")
            return
        sm.set_session_title(active_id, title)
        ctx.print(f"{p}Session named: {title}")
        return

    if len(parts) >= 3 and parts[1] == "resume":
        target = command.partition("resume")[2].strip()
        if not target:
            ctx.print(f"{p}Usage: /session resume <id-or-name>")
            return
        try:
            session = sm.resolve_session_identifier(target)
        except ValueError as ex:
            ctx.print(f"{p}{ex}")
            return
        if session is None:
            ctx.print(f"{p}Session not found: {target}")
            return
        resolved_id = session["id"]
        ctx.memory.active_session_id = resolved_id
        new_messages = ctx.memory.load_messages(resolved_id)
        ctx.on_session_reset(resolved_id, new_messages)
        summary = sm.build_session_summary(resolved_id)
        ctx.print(
            f"{p}Resumed session {summary['title']} "
            f"[{ctx.session_controller.short_id(resolved_id)}] "
            f"(id={resolved_id}, {len(new_messages)} messages)"
        )
        for line in ctx.session_controller.format_resumed_summary_lines(summary):
            ctx.print(line)
        return

    if len(parts) == 2 and parts[1] == "fork":
        active_id = ctx.memory.active_session_id
        if active_id is None:
            ctx.print(f"{p}No active session to fork")
            return
        source_id = active_id
        fork_id = sm.fork_session(source_id)
        ctx.memory.active_session_id = fork_id
        ctx.on_session_reset(fork_id, ctx.memory.load_messages(fork_id))
        ctx.print(f"{p}Forked session {source_id} -> {fork_id}")
        return

    ctx.print(
        f"{p}Usage: /session | /session new [title] | /session list [limit] | "
        "/session name <title> | /session resume <id-or-name> | /session fork"
    )
