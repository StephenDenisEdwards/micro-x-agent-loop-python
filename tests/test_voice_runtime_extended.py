"""Extended tests for VoiceRuntime — edge cases, error paths, JSON parsing."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from micro_x_agent_loop.tool import ToolResult
from micro_x_agent_loop.voice_runtime import VoiceRuntime

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _JsonTool:
    def __init__(self, payload: dict[str, Any], *, name_suffix: str = ""):
        self._payload = payload
        self._name_suffix = name_suffix

    @property
    def name(self) -> str:
        return f"stt{self._name_suffix}"

    @property
    def description(self) -> str:
        return "json tool"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        return ToolResult(text=json.dumps(self._payload))


class _FailTool:
    @property
    def name(self) -> str:
        return "fail_tool"

    @property
    def description(self) -> str:
        return "always fails"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        raise RuntimeError("tool error")


class _FakeIngress:
    def __init__(self, events: list[dict[str, Any]]):
        self._events = events

    async def stream_events(self, *, session_id: str, since_seq: int):
        for event in self._events:
            yield event
        while True:
            await asyncio.sleep(0.05)


def _make_tool_map() -> dict[str, Any]:
    return {
        "stt-server__stt_start_session": _JsonTool({"session_id": "s-1"}),
        "stt-server__stt_stop_session": _JsonTool({"ok": True}),
        "stt-server__stt_get_session": _JsonTool({
            "status": "running", "next_seq": 1, "stable_chunk_count": 2,
            "error_count": 0, "latest_transcript": "hello",
        }),
        "stt-server__stt_list_devices": _JsonTool({"capture": [], "render": []}),
        "stt-server__stt_get_updates": _JsonTool({"events": []}),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class VoiceRuntimeStartTests(unittest.TestCase):
    def test_missing_tools(self) -> None:
        """Start with missing tools returns error message."""
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        msg = asyncio.run(runtime.start())
        self.assertIn("Voice unavailable", msg)
        self.assertIn("missing", msg)

    def test_invalid_source(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map=_make_tool_map(),
            on_utterance=AsyncMock(),
            ingress=_FakeIngress([]),
        )
        msg = asyncio.run(runtime.start(source="invalid"))
        self.assertIn("microphone or loopback", msg)

    def test_double_start(self) -> None:
        async def scenario() -> str:
            runtime = VoiceRuntime(
                line_prefix=">> ",
                tool_map=_make_tool_map(),
                on_utterance=AsyncMock(),
                ingress=_FakeIngress([]),
            )
            await runtime.start("microphone")
            return await runtime.start("microphone")

        msg = asyncio.run(scenario())
        self.assertIn("already running", msg)

    def test_start_no_session_id(self) -> None:
        """Start fails when tool response has no session_id."""
        tool_map = _make_tool_map()
        tool_map["stt-server__stt_start_session"] = _JsonTool({})
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map=tool_map,
            on_utterance=AsyncMock(),
            ingress=_FakeIngress([]),
        )
        msg = asyncio.run(runtime.start())
        self.assertIn("missing session_id", msg)

    def test_start_with_loopback(self) -> None:
        async def scenario() -> str:
            runtime = VoiceRuntime(
                line_prefix=">> ",
                tool_map=_make_tool_map(),
                on_utterance=AsyncMock(),
                ingress=_FakeIngress([]),
            )
            msg = await runtime.start("loopback")
            await runtime.stop()
            return msg

        msg = asyncio.run(scenario())
        self.assertIn("Voice started", msg)
        self.assertIn("loopback", msg)

    def test_start_with_mic_device(self) -> None:
        async def scenario() -> str:
            runtime = VoiceRuntime(
                line_prefix=">> ",
                tool_map=_make_tool_map(),
                on_utterance=AsyncMock(),
                ingress=_FakeIngress([]),
            )
            msg = await runtime.start(
                "microphone", mic_device_id="dev-1", mic_device_name="My Mic"
            )
            await runtime.stop()
            return msg

        msg = asyncio.run(scenario())
        self.assertIn("Voice started", msg)
        self.assertIn("My Mic", msg)
        self.assertIn("dev-1", msg)


class VoiceRuntimeStopTests(unittest.TestCase):
    def test_stop_when_not_running(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        msg = asyncio.run(runtime.stop())
        self.assertIn("already stopped", msg)

    def test_shutdown_when_not_running(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        # Should not raise
        asyncio.run(runtime.shutdown())


class VoiceRuntimeStatusTests(unittest.TestCase):
    def test_status_when_stopped(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        msg = asyncio.run(runtime.status())
        self.assertIn("stopped", msg)

    def test_status_no_status_tool(self) -> None:
        """Status with missing status tool returns basic info."""
        tool_map = _make_tool_map()

        async def scenario() -> str:
            runtime = VoiceRuntime(
                line_prefix=">> ",
                tool_map=tool_map,
                on_utterance=AsyncMock(),
                ingress=_FakeIngress([]),
            )
            await runtime.start()
            # Now remove the status tool after start to simulate missing tool
            del tool_map["stt-server__stt_get_session"]
            msg = await runtime.status()
            await runtime.stop()
            return msg

        msg = asyncio.run(scenario())
        self.assertIn("Voice running", msg)

    def test_status_long_transcript_truncated(self) -> None:
        """Long latest_transcript in status is truncated."""
        tool_map = _make_tool_map()
        tool_map["stt-server__stt_get_session"] = _JsonTool({
            "status": "running", "next_seq": 5, "stable_chunk_count": 1,
            "error_count": 0, "latest_transcript": "x" * 100,
        })

        async def scenario() -> str:
            runtime = VoiceRuntime(
                line_prefix=">> ",
                tool_map=tool_map,
                on_utterance=AsyncMock(),
                ingress=_FakeIngress([]),
            )
            await runtime.start()
            msg = await runtime.status()
            await runtime.stop()
            return msg

        msg = asyncio.run(scenario())
        self.assertIn("...", msg)


class VoiceRuntimeEventsTests(unittest.TestCase):
    def test_events_when_stopped(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        msg = asyncio.run(runtime.events())
        self.assertIn("stopped", msg)

    def test_events_no_updates_tool(self) -> None:
        tool_map = _make_tool_map()

        async def scenario() -> str:
            runtime = VoiceRuntime(
                line_prefix=">> ",
                tool_map=tool_map,
                on_utterance=AsyncMock(),
                ingress=_FakeIngress([]),
            )
            await runtime.start()
            # Remove after start
            del tool_map["stt-server__stt_get_updates"]
            msg = await runtime.events()
            await runtime.stop()
            return msg

        msg = asyncio.run(scenario())
        self.assertIn("missing", msg)


class VoiceRuntimeDevicesTests(unittest.TestCase):
    def test_devices_no_tool(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        msg = asyncio.run(runtime.devices())
        self.assertIn("missing", msg)

    def test_devices_success(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map=_make_tool_map(),
            on_utterance=AsyncMock(),
        )
        msg = asyncio.run(runtime.devices())
        data = json.loads(msg)
        self.assertIn("capture", data)


class VoiceRuntimeIsRunningTests(unittest.TestCase):
    def test_not_running_initially(self) -> None:
        runtime = VoiceRuntime(
            line_prefix=">> ",
            tool_map={},
            on_utterance=AsyncMock(),
        )
        self.assertFalse(runtime.is_running)


class ParseJsonObjectTests(unittest.TestCase):
    def _parse(self, raw: str) -> dict:
        runtime = VoiceRuntime(
            line_prefix="", tool_map={}, on_utterance=AsyncMock(),
        )
        return runtime._parse_json_object(raw)

    def test_plain_json(self) -> None:
        self.assertEqual({"a": 1}, self._parse('{"a": 1}'))

    def test_markdown_fenced(self) -> None:
        raw = "```json\n{\"b\": 2}\n```"
        self.assertEqual({"b": 2}, self._parse(raw))

    def test_embedded_json(self) -> None:
        raw = "Some text before {\"c\": 3} and after"
        self.assertEqual({"c": 3}, self._parse(raw))

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._parse("not json at all")


class AsyncMock:
    """Simple async callable mock."""
    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


if __name__ == "__main__":
    unittest.main()
