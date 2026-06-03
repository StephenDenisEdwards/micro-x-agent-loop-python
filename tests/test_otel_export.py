"""Phase 4 — OpenTelemetry span mapping (pure, SDK-free)."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.otel_export import build_otel_exporter, build_span_spec


class SpanSpecMappingTests(unittest.TestCase):
    def test_api_call_maps_to_genai_chat_span(self) -> None:
        spec = build_span_spec(
            "metric.api_call",
            {
                "session_id": "s1", "provider": "anthropic", "model": "claude-x",
                "input_tokens": 1200, "output_tokens": 300, "duration_ms": 1100,
                "estimated_cost_usd": 0.004, "call_type": "main", "stop_reason": "end_turn",
                "turn_number": 2,
            },
        )
        assert spec is not None
        self.assertEqual(spec.kind, "llm")
        self.assertEqual(spec.session_id, "s1")
        self.assertEqual(spec.name, "chat claude-x")
        self.assertEqual(spec.duration_ms, 1100)
        self.assertEqual(spec.attributes["gen_ai.system"], "anthropic")
        self.assertEqual(spec.attributes["gen_ai.request.model"], "claude-x")
        self.assertEqual(spec.attributes["gen_ai.usage.input_tokens"], 1200)
        self.assertEqual(spec.attributes["gen_ai.usage.output_tokens"], 300)
        self.assertEqual(spec.attributes["gen_ai.operation.name"], "chat")

    def test_tool_execution_maps_to_tool_span(self) -> None:
        spec = build_span_spec(
            "metric.tool_execution",
            {"session_id": "s1", "tool_name": "web_fetch", "result_chars": 500,
             "duration_ms": 320, "is_error": False, "was_summarized": True, "turn_number": 1},
        )
        assert spec is not None
        self.assertEqual(spec.kind, "tool")
        self.assertEqual(spec.name, "execute_tool web_fetch")
        self.assertEqual(spec.attributes["gen_ai.tool.name"], "web_fetch")
        self.assertEqual(spec.attributes["gen_ai.operation.name"], "execute_tool")
        self.assertTrue(spec.attributes["micro_x.was_summarized"])

    def test_non_span_events_return_none(self) -> None:
        self.assertIsNone(build_span_spec("routing.decision", {"session_id": "s1"}))
        self.assertIsNone(build_span_spec("mode.analyzed", {"session_id": "s1"}))
        self.assertIsNone(build_span_spec("llm.call", {"session_id": "s1"}))

    def test_build_exporter_is_graceful(self) -> None:
        # Construction must never raise, whether or not the SDK is installed:
        # returns None (no SDK) or a working exporter (SDK present).
        result = build_otel_exporter("http://localhost:4318/v1/traces")
        self.assertTrue(result is None or hasattr(result, "shutdown"))
        if result is not None:
            # Exporting against a dead endpoint must not raise either.
            result("metric.api_call", {"session_id": "s1", "model": "m", "duration_ms": 10})
            result("metric.session_summary", {"session_id": "s1"})
            result.shutdown()


if __name__ == "__main__":
    unittest.main()
