from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass
class VoiceStartOptions:
    source: str = "microphone"
    mic_device_id: str | None = None
    mic_device_name: str | None = None
    chunk_seconds: int | None = None
    endpointing_ms: int | None = None
    utterance_end_ms: int | None = None


def parse_voice_command(command: str) -> list[str]:
    return shlex.split(command)


def parse_voice_start_options(parts: list[str], *, line_prefix: str) -> tuple[VoiceStartOptions | None, str | None]:
    opts = VoiceStartOptions()
    idx = 2
    if len(parts) >= 3 and not parts[2].startswith("--"):
        opts.source = parts[2].lower()
        idx = 3

    while idx < len(parts):
        token = parts[idx]
        if token == "--mic-device-id":
            if idx + 1 >= len(parts):
                return None, f"{line_prefix}Usage: /voice start ... --mic-device-id <id>"
            opts.mic_device_id = parts[idx + 1]
            idx += 2
            continue
        if token == "--mic-device-name":
            if idx + 1 >= len(parts):
                return None, f"{line_prefix}Usage: /voice start ... --mic-device-name <name>"
            name_tokens: list[str] = []
            j = idx + 1
            while j < len(parts) and not parts[j].startswith("--"):
                name_tokens.append(parts[j])
                j += 1
            if not name_tokens:
                return None, f"{line_prefix}Usage: /voice start ... --mic-device-name <name>"
            opts.mic_device_name = " ".join(name_tokens).strip().strip('"\'')
            idx = j
            continue
        if token == "--chunk-seconds":
            if idx + 1 >= len(parts):
                return None, f"{line_prefix}Usage: /voice start ... --chunk-seconds <n>"
            try:
                opts.chunk_seconds = int(parts[idx + 1])
            except ValueError:
                return None, f"{line_prefix}chunk-seconds must be an integer"
            idx += 2
            continue
        if token == "--endpointing-ms":
            if idx + 1 >= len(parts):
                return None, f"{line_prefix}Usage: /voice start ... --endpointing-ms <n>"
            try:
                opts.endpointing_ms = int(parts[idx + 1])
            except ValueError:
                return None, f"{line_prefix}endpointing-ms must be an integer"
            idx += 2
            continue
        if token == "--utterance-end-ms":
            if idx + 1 >= len(parts):
                return None, f"{line_prefix}Usage: /voice start ... --utterance-end-ms <n>"
            try:
                opts.utterance_end_ms = int(parts[idx + 1])
            except ValueError:
                return None, f"{line_prefix}utterance-end-ms must be an integer"
            idx += 2
            continue
        return None, (
            f"{line_prefix}Usage: /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>]"
        )

    return opts, None
