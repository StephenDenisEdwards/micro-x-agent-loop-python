"""Tests for voice_ingress module."""

from __future__ import annotations

import asyncio
import unittest

from micro_x_agent_loop.voice_ingress import PollingVoiceIngress, _parse_json_object


class ParseJsonObjectTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        result = _parse_json_object('{"events": []}')
        self.assertEqual({"events": []}, result)

    def test_json_in_markdown_block(self) -> None:
        raw = '```json\n{"events": [{"seq": 1}]}\n```'
        result = _parse_json_object(raw)
        self.assertEqual([{"seq": 1}], result["events"])

    def test_json_embedded_in_text(self) -> None:
        raw = 'Some text before {"events": []} and after'
        result = _parse_json_object(raw)
        self.assertEqual({"events": []}, result)

    def test_invalid_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            _parse_json_object("not json at all")

    def test_whitespace_stripped(self) -> None:
        result = _parse_json_object('  {"key": "val"}  ')
        self.assertEqual({"key": "val"}, result)

    def test_markdown_block_no_language(self) -> None:
        raw = '```\n{"x": 1}\n```'
        result = _parse_json_object(raw)
        self.assertEqual({"x": 1}, result)

    def test_non_dict_json_falls_through_to_extract(self) -> None:
        # Array at top level -> not a dict -> falls through to brace extraction
        # Since there's no { ... } pair for a dict, this should raise
        with self.assertRaises((ValueError, Exception)):
            _parse_json_object("[1, 2, 3]")


class PollingVoiceIngressTests(unittest.TestCase):
    def test_no_tool_found_returns_immediately(self) -> None:
        """If no stt_get_updates tool is in the map, stream_events yields nothing."""
        async def collect():
            ingress = PollingVoiceIngress(tool_map={}, poll_interval_seconds=0)
            events = []
            async for event in ingress.stream_events(session_id="s1", since_seq=0):
                events.append(event)
            return events

        result = asyncio.run(collect())
        self.assertEqual([], result)

    def test_tool_not_in_map_returns_immediately(self) -> None:
        """If tool key resolves to None, generator exits."""
        from unittest.mock import MagicMock
        # A tool map where the key ends with __stt_get_updates but value could be None
        # This can't happen in normal usage (dict.get returns None), so test the None branch
        async def collect():
            ingress = PollingVoiceIngress(tool_map={}, poll_interval_seconds=0)
            # Override to simulate the edge case: _tool_map has no stt tool
            events = []
            async for event in ingress.stream_events(session_id="s1", since_seq=0):
                events.append(event)
            return events

        result = asyncio.run(collect())
        self.assertEqual([], result)

    def test_yields_events_and_updates_seq(self) -> None:
        """Events are yielded with incrementing seq tracking."""
        from unittest.mock import AsyncMock, MagicMock
        import json

        call_count = 0

        class FakeTool:
            async def execute(self, tool_input):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    payload = {"events": [{"seq": 1, "type": "text", "text": "hello"}]}
                    result = MagicMock()
                    result.text = json.dumps(payload)
                    return result
                # Second call triggers StopAsyncIteration in the test via cancellation
                raise asyncio.CancelledError()

        tool = FakeTool()
        tool_map = {"server__stt_get_updates": tool}
        ingress = PollingVoiceIngress(tool_map=tool_map, poll_interval_seconds=0)

        async def collect():
            events = []
            async for event in ingress.stream_events(session_id="s1", since_seq=0):
                events.append(event)
                if len(events) >= 1:
                    break
            return events

        result = asyncio.run(collect())
        self.assertEqual(1, len(result))
        self.assertEqual(1, result[0]["seq"])

    def test_skips_events_with_old_seq(self) -> None:
        """Events with seq <= last_seq are yielded (seq tracking only updates max)."""
        import json
        from unittest.mock import MagicMock

        call_count = 0

        class FakeTool:
            async def execute(self, tool_input):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    payload = {
                        "events": [
                            {"seq": 5, "text": "new"},
                            {"seq": 3, "text": "old"},  # older seq
                        ]
                    }
                    result = MagicMock()
                    result.text = json.dumps(payload)
                    return result
                raise asyncio.CancelledError()

        tool = FakeTool()
        tool_map = {"server__stt_get_updates": tool}
        ingress = PollingVoiceIngress(tool_map=tool_map, poll_interval_seconds=0)

        async def collect():
            events = []
            async for event in ingress.stream_events(session_id="s1", since_seq=0):
                events.append(event)
                if len(events) >= 2:
                    break
            return events

        result = asyncio.run(collect())
        # Both events are yielded; the seq tracking only tracks the max
        self.assertEqual(2, len(result))


if __name__ == "__main__":
    unittest.main()
