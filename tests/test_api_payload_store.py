"""Tests for ApiPayloadStore — ring buffer for API payloads."""

import time
import unittest

from micro_x_agent_loop.api_payload_store import ApiPayload, ApiPayloadStore
from micro_x_agent_loop.usage import UsageResult


def _make_payload(model: str = "m", stop_reason: str = "end_turn") -> ApiPayload:
    return ApiPayload(
        timestamp=time.time(),
        model=model,
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "hi"}],
        tools_count=5,
        response_message={"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
        stop_reason=stop_reason,
        usage=UsageResult(input_tokens=100, output_tokens=50),
    )


class ApiPayloadStoreTests(unittest.TestCase):
    def test_empty_store_returns_none(self) -> None:
        store = ApiPayloadStore()
        self.assertIsNone(store.get(0))
        self.assertEqual(0, len(store))

    def test_record_and_get_most_recent(self) -> None:
        store = ApiPayloadStore()
        p = _make_payload(model="claude")
        store.record(p)
        self.assertEqual(1, len(store))
        result = store.get(0)
        self.assertIsNotNone(result)
        self.assertEqual("claude", result.model)

    def test_get_by_index(self) -> None:
        store = ApiPayloadStore()
        store.record(_make_payload(model="first"))
        store.record(_make_payload(model="second"))
        store.record(_make_payload(model="third"))
        self.assertEqual("third", store.get(0).model)
        self.assertEqual("second", store.get(1).model)
        self.assertEqual("first", store.get(2).model)

    def test_get_out_of_range_returns_none(self) -> None:
        store = ApiPayloadStore()
        store.record(_make_payload())
        self.assertIsNone(store.get(1))
        self.assertIsNone(store.get(-1))

    def test_ring_buffer_overflow(self) -> None:
        store = ApiPayloadStore(max_size=3)
        for i in range(5):
            store.record(_make_payload(model=f"m{i}"))
        self.assertEqual(3, len(store))
        # Most recent should be m4, oldest should be m2
        self.assertEqual("m4", store.get(0).model)
        self.assertEqual("m3", store.get(1).model)
        self.assertEqual("m2", store.get(2).model)
        self.assertIsNone(store.get(3))

    def test_payload_fields(self) -> None:
        store = ApiPayloadStore()
        p = _make_payload(stop_reason="tool_use")
        store.record(p)
        result = store.get(0)
        self.assertEqual("tool_use", result.stop_reason)
        self.assertEqual(5, result.tools_count)
        self.assertEqual(100, result.usage.input_tokens)


if __name__ == "__main__":
    unittest.main()
