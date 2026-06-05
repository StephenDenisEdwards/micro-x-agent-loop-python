"""`/voice` — voice-runtime control commands (start/status/devices/events/stop)."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext
from micro_x_agent_loop.commands.voice_command import parse_voice_command, parse_voice_start_options

_USAGE = (
    "Usage: /voice start [microphone|loopback] "
    "[--mic-device-id <id>] [--mic-device-name <name>] "
    "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
    "/voice status | /voice devices | /voice events [limit] | /voice stop"
)


async def handle_voice(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    runtime = ctx.voice_runtime
    if runtime is None:
        ctx.print(f"{p}Voice runtime is not available.")
        return
    try:
        parts = parse_voice_command(command)
    except ValueError:
        ctx.print(f"{p}Invalid command syntax")
        return
    if len(parts) == 1:
        ctx.print(f"{p}{_USAGE}")
        return

    action = parts[1].lower()
    if action == "start":
        opts, error = parse_voice_start_options(parts, line_prefix=p)
        if error:
            ctx.print(error)
            return
        assert opts is not None
        ctx.print(
            await runtime.start(
                opts.source,
                opts.mic_device_id,
                opts.mic_device_name,
                opts.chunk_seconds,
                opts.endpointing_ms,
                opts.utterance_end_ms,
            )
        )
        return

    if action == "status":
        ctx.print(await runtime.status())
        return

    if action == "devices":
        ctx.print(await runtime.devices())
        return

    if action == "events":
        limit = 50
        if len(parts) >= 3:
            try:
                limit = int(parts[2])
            except ValueError:
                ctx.print(f"{p}Usage: /voice events [limit]")
                return
        ctx.print(await runtime.events(limit))
        return

    if action == "stop":
        ctx.print(await runtime.stop())
        return

    ctx.print(f"{p}{_USAGE}")
