"""`/help`, `/command`, and the unknown-command handler."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def on_help(ctx: CommandContext) -> None:
    print_help(ctx)


def on_unknown_command(ctx: CommandContext, trimmed: str) -> None:
    ctx.print(f"{ctx.line_prefix}Unknown local command: {trimmed}")


def print_help(ctx: CommandContext) -> None:
    p = ctx.line_prefix
    ctx.print(f"{p}Available commands:")
    ctx.print(f"{p}- /help")
    ctx.print(f"{p}- /prompt <filename>")
    ctx.print(f"{p}- /command")
    ctx.print(f"{p}- /command <name> [arguments]")
    ctx.print(f"{p}- /cost")
    ctx.print(f"{p}- /cost reconcile [days] [--start YYYY-MM-DD] [--end YYYY-MM-DD]")
    ctx.print(f"{p}- /replay [session_id] [--full] — step-through (--full = verbatim request)")
    ctx.print(f"{p}- /feedback +1|-1|<text> — rate the last assistant turn")
    ctx.print(
        f"{p}- /voice start [microphone|loopback] "
        "[--mic-device-id <id>] [--mic-device-name <name>] "
        "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>]"
    )
    ctx.print(f"{p}- /voice status")
    ctx.print(f"{p}- /voice devices")
    ctx.print(f"{p}- /voice events [limit]")
    ctx.print(f"{p}- /voice stop")
    ctx.print(f"{p}- /tools mcp")
    ctx.print(f"{p}- /tool")
    ctx.print(f"{p}- /tool <name>")
    ctx.print(f"{p}- /tool <name> schema")
    ctx.print(f"{p}- /tool <name> config")
    ctx.print(f"{p}- /tool delete <name>")
    ctx.print(f"{p}- /routing")
    ctx.print(f"{p}- /routing tasks | providers | stages | recent")
    ctx.print(f"{p}- /compact [tail N]")
    ctx.print(f"{p}- /codegen-task-list [verbose]")
    ctx.print(f"{p}- /console-log-level [TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL|OFF]")
    ctx.print(f"{p}- /debug show-api-payload [N]")
    if ctx.user_memory_enabled:
        ctx.print(f"{p}- /memory")
        ctx.print(f"{p}- /memory list")
        ctx.print(f"{p}- /memory edit")
        ctx.print(f"{p}- /memory reset")
    if ctx.memory_enabled:
        ctx.print(f"{p}- /session")
        ctx.print(f"{p}- /session new [title]")
        ctx.print(f"{p}- /session list [limit]")
        ctx.print(f"{p}- /session name <title>")
        ctx.print(f"{p}- /session resume <id-or-name>")
        ctx.print(f"{p}- /session fork")
        ctx.print(f"{p}- /rewind <checkpoint_id>")
        ctx.print(f"{p}- /checkpoint list [limit]")
        ctx.print(f"{p}- /checkpoint rewind <checkpoint_id>")
    else:
        ctx.print(f"{p}Memory commands are available when MemoryEnabled=true (see operations/config.md).")


async def handle_command(ctx: CommandContext, command: str) -> str | None:
    """Handle `/command`. Returns prompt text to execute, or None if handled locally."""
    parts = command.split(None, 2)
    if len(parts) == 1:
        print_command_list(ctx)
        return None

    name = parts[1]
    prompt = ctx.prompt_command_store.load_command(name)
    if prompt is None:
        ctx.print(f"{ctx.line_prefix}Unknown command: {name}")
        print_command_list(ctx)
        return None

    arguments = parts[2] if len(parts) > 2 else ""
    prompt = prompt.replace("$ARGUMENTS", arguments)
    return prompt


def print_command_list(ctx: CommandContext) -> None:
    commands = ctx.prompt_command_store.list_commands()
    if not commands:
        ctx.print(f"{ctx.line_prefix}No commands found. Add .md files to the .commands/ directory.")
        return
    max_name = max(len(name) for name, _ in commands)
    ctx.print(f"{ctx.line_prefix}Available commands:")
    for name, description in commands:
        ctx.print(f"{ctx.line_prefix}  {name:<{max_name}}  {description}")
