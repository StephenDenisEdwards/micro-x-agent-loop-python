import asyncio
import json
import unittest
from typing import Any

from micro_x_agent_loop.voice_runtime import VoiceRuntime


class _JsonTool:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    @property
    def name(self) -> str:
        return "json_tool"

    @property
    def description(self) -> str:
        return "json tool"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def execute(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(self._payload)


class _FakeIngress:
    def __init__(self, events: list[dict[str, Any]]):
        self._events = events

    async def stream_events(self, *, session_id: str, since_seq: int):
        for event in self._events:
            yield event
        while True:
            await asyncio.sleep(0.05)


class VoiceRuntimeTests(unittest.TestCase):
    def test_runtime_processes_final_utterance(self) -> None:
        captured: list[str] = []

        async def on_utterance(text: str) -> None:
            captured.append(text)

        tool_map = {
            "interview-assist__stt_start_session": _JsonTool({"session_id": "s-1"}),
            "interview-assist__stt_stop_session": _JsonTool({"ok": True}),
            "interview-assist__stt_get_session": _JsonTool({"status": "running", "next_seq": 2}),
            "interview-assist__stt_list_devices": _JsonTool({"capture": [], "render": []}),
            "interview-assist__stt_get_updates": _JsonTool({"events": []}),
        }
        ingress = _FakeIngress([
            {"seq": 1, "type": "utterance_final", "text": "hello world"},
            {"seq": 2, "type": "info", "message": "noop"},
        ])
        runtime = VoiceRuntime(
            line_prefix="assistant> ",
            tool_map=tool_map,
            on_utterance=on_utterance,
            ingress=ingress,
        )

        async def scenario() -> None:
            msg = await runtime.start("microphone")
            self.assertIn("Voice started", msg)
            await asyncio.sleep(0.2)
            status = await runtime.status()
            self.assertIn("processed=1", status)
            await runtime.stop()

        asyncio.run(scenario())
        self.assertEqual(["hello world"], captured)


if __name__ == "__main__":
    unittest.main()
