from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.voice_ingress import PollingVoiceIngress, VoiceIngress


class VoiceRuntime:
    _REQUIRED_TOOLS = {
        "start": "__stt_start_session",
        "updates": "__stt_get_updates",
        "stop": "__stt_stop_session",
        "status": "__stt_get_session",
        "devices": "__stt_list_devices",
    }
    # Retained for compatibility; current MCP STT session mode is streaming.
    _MIN_CHUNK_SECONDS = 1
    _DEFAULT_CHUNK_SECONDS = 3
    _DEFAULT_ENDPOINTING_MS = 500
    _DEFAULT_UTTERANCE_END_MS = 1500

    def __init__(
        self,
        *,
        line_prefix: str,
        tool_map: dict[str, Tool],
        on_utterance: Callable[[str], Awaitable[None]],
        ingress: VoiceIngress | None = None,
    ) -> None:
        self._line_prefix = line_prefix
        self._tool_map = tool_map
        self._on_utterance = on_utterance
        self._ingress = ingress or PollingVoiceIngress(tool_map=tool_map)
        self._session_id: str | None = None
        self._last_seq = 0
        self._poll_task: asyncio.Task | None = None
        self._consumer_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[tuple[str, float]] = asyncio.Queue()
        self._metrics = {
            "queued_count": 0,
            "processed_count": 0,
            "avg_queue_wait_ms": 0.0,
            "avg_process_ms": 0.0,
            "last_process_ms": 0.0,
        }

    @property
    def is_running(self) -> bool:
        return self._session_id is not None

    async def start(
        self,
        source: str = "microphone",
        mic_device_id: str | None = None,
        mic_device_name: str | None = None,
        chunk_seconds: int | None = None,
        endpointing_ms: int | None = None,
        utterance_end_ms: int | None = None,
    ) -> str:
        tool_names = self._resolve_tool_names()
        missing = [name for name, resolved in tool_names.items() if resolved is None]
        if missing:
            return (
                f"{self._line_prefix}Voice unavailable: missing MCP tools "
                f"{', '.join('stt_' + n for n in missing)}"
            )

        if source not in {"microphone", "loopback"}:
            return f"{self._line_prefix}Voice source must be microphone or loopback"

        if self._session_id is not None:
            return f"{self._line_prefix}Voice is already running (session={self._session_id})"

        effective_chunk_seconds = max(
            self._MIN_CHUNK_SECONDS,
            int(chunk_seconds or self._DEFAULT_CHUNK_SECONDS),
        )
        start_input: dict[str, Any] = {
            "source": source,
            "chunk_seconds": effective_chunk_seconds,
            "endpointing_ms": max(0, int(endpointing_ms or self._DEFAULT_ENDPOINTING_MS)),
            "utterance_end_ms": max(0, int(utterance_end_ms or self._DEFAULT_UTTERANCE_END_MS)),
        }
        if source == "microphone" and mic_device_id:
            start_input["mic_device_id"] = mic_device_id
        if source == "microphone" and mic_device_name:
            start_input["mic_device_name"] = mic_device_name
        payload = await self._call_json_tool(tool_names["start"] or "", start_input)
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            return f"{self._line_prefix}Voice failed: start response missing session_id"

        self._session_id = session_id
        self._last_seq = 0
        self._queue = asyncio.Queue()
        self._metrics = {
            "queued_count": 0,
            "processed_count": 0,
            "avg_queue_wait_ms": 0.0,
            "avg_process_ms": 0.0,
            "last_process_ms": 0.0,
        }
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        details = (
            f"chunk={start_input.get('chunk_seconds')} "
            f"endpointing_ms={start_input.get('endpointing_ms')} "
            f"utterance_end_ms={start_input.get('utterance_end_ms')}"
        )
        details += " stream_mode=true"
        if source == "microphone" and mic_device_name:
            details += f" mic_device_name={mic_device_name!r}"
        if source == "microphone" and mic_device_id:
            details += f" mic_device_id={mic_device_id}"
        return f"{self._line_prefix}Voice started ({source}) session={session_id} [{details}]"

    async def status(self) -> str:
        if self._session_id is None:
            return f"{self._line_prefix}Voice is stopped"

        tool_names = self._resolve_tool_names()
        status_tool = tool_names["status"]
        if status_tool is None:
            return f"{self._line_prefix}Voice running (session={self._session_id})"
        try:
            payload = await self._call_json_tool(status_tool, {"session_id": self._session_id})
            latest = str(payload.get("latest_transcript", "")).strip()
            if len(latest) > 60:
                latest = latest[:57] + "..."
            return (
                f"{self._line_prefix}Voice session={self._session_id} "
                f"status={payload.get('status')} queue={self._queue.qsize()} "
                f"next_seq={payload.get('next_seq')} stable={payload.get('stable_chunk_count', 0)} "
                f"errors={payload.get('error_count', 0)} queued={self._metrics['queued_count']} "
                f"processed={self._metrics['processed_count']} "
                f"avg_wait_ms={self._metrics['avg_queue_wait_ms']:.0f} "
                f"avg_process_ms={self._metrics['avg_process_ms']:.0f} latest='{latest}'"
            )
        except Exception as ex:
            return f"{self._line_prefix}Voice status check failed: {ex}"

    async def stop(self) -> str:
        if self._session_id is None:
            return f"{self._line_prefix}Voice is already stopped"

        session_id = self._session_id
        tool_names = self._resolve_tool_names()
        stop_tool = tool_names["stop"]

        self._session_id = None
        for task in (self._poll_task, self._consumer_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._poll_task = None
        self._consumer_task = None

        if stop_tool is not None:
            with contextlib.suppress(Exception):
                await self._call_json_tool(stop_tool, {"session_id": session_id})
        return f"{self._line_prefix}Voice stopped (session={session_id})"

    async def events(self, limit: int = 50) -> str:
        if self._session_id is None:
            return f"{self._line_prefix}Voice is stopped"

        tool_names = self._resolve_tool_names()
        updates_tool = tool_names["updates"]
        if updates_tool is None:
            return f"{self._line_prefix}Voice unavailable: missing MCP tool stt_get_updates"

        bounded_limit = max(1, min(limit, 500))
        payload = await self._call_json_tool(
            updates_tool,
            {
                "session_id": self._session_id,
                "since_seq": 0,
                "limit": bounded_limit,
            },
        )
        return json.dumps(payload, ensure_ascii=True, indent=2)

    async def devices(self) -> str:
        tool_names = self._resolve_tool_names()
        devices_tool = tool_names["devices"]
        if devices_tool is None:
            return f"{self._line_prefix}Voice unavailable: missing MCP tool stt_list_devices"
        payload = await self._call_json_tool(devices_tool, {})
        return json.dumps(payload, ensure_ascii=True, indent=2)

    async def shutdown(self) -> None:
        if self._session_id is not None:
            await self.stop()

    async def _poll_loop(self) -> None:
        if self._session_id is None:
            return
        session_id = self._session_id
        try:
            async for event in self._ingress.stream_events(session_id=session_id, since_seq=self._last_seq):
                if self._session_id is None:
                    return
                seq = int(event.get("seq", 0))
                if seq > self._last_seq:
                    self._last_seq = seq
                if event.get("type") == "utterance_final":
                    text = str(event.get("text", "")).strip()
                    if text:
                        self._metrics["queued_count"] += 1
                        await self._queue.put((text, time.perf_counter()))
                        print(f"{self._line_prefix}[voice] queued: {text}")
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            print(f"{self._line_prefix}Voice polling failed: {ex}")
            self._session_id = None

    async def _consumer_loop(self) -> None:
        try:
            while self._session_id is not None:
                text, queued_at = await self._queue.get()
                if self._session_id is None:
                    return
                print(f"{self._line_prefix}[voice] processing")
                wait_ms = (time.perf_counter() - queued_at) * 1000
                process_start = time.perf_counter()
                await self._on_utterance(text)
                process_ms = (time.perf_counter() - process_start) * 1000

                self._metrics["processed_count"] += 1
                n = self._metrics["processed_count"]
                self._metrics["avg_queue_wait_ms"] = (
                    (self._metrics["avg_queue_wait_ms"] * (n - 1) + wait_ms) / n
                )
                self._metrics["avg_process_ms"] = (
                    (self._metrics["avg_process_ms"] * (n - 1) + process_ms) / n
                )
                self._metrics["last_process_ms"] = process_ms
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            # Keep voice runtime healthy even if a single utterance fails.
            print(f"{self._line_prefix}Voice consumer failed: {ex}")

    def _resolve_tool_names(self) -> dict[str, str | None]:
        resolved: dict[str, str | None] = {}
        for key, suffix in self._REQUIRED_TOOLS.items():
            resolved[key] = next((name for name in self._tool_map if name.endswith(suffix)), None)
        return resolved

    async def _call_json_tool(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        tool = self._tool_map.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found: {tool_name}")
        raw = await tool.execute(tool_input)
        return self._parse_json_object(raw)

    def _parse_json_object(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("Tool response was not valid JSON object")
