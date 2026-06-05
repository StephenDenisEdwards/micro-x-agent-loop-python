"""`/console-log-level` — change the live console log consumer level."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_console_log_level(ctx: CommandContext, command: str) -> None:
    from micro_x_agent_loop.logging_config import ConsoleLogConsumer

    p = ctx.line_prefix
    consumer = ConsoleLogConsumer.get_instance()
    if consumer is None:
        ctx.print(f"{p}No console log consumer is active.")
        return

    parts = command.split()
    if len(parts) == 1:
        ctx.print(f"{p}Console log level: {consumer.level}")
        return

    valid_levels = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL", "OFF")
    new_level = parts[1].upper()
    if new_level not in valid_levels:
        ctx.print(f"{p}Invalid level: {parts[1]}. Valid: {', '.join(valid_levels)}")
        return

    consumer.set_level(new_level)
    ctx.print(f"{p}Console log level set to {new_level}")
