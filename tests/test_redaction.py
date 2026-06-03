"""Phase 3 — PII/secret redaction on the observability persistence path."""

from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.redaction import NullRedactor, RegexRedactor, build_redactor


class RegexRedactorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = RegexRedactor()

    def test_scrubs_common_secrets(self) -> None:
        cases = [
            "sk-ant-api03-abcdefghij1234567890ABCDEFG",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "eyJhbGciOiJIUzI1Ni9.eyJzdWIiOiIxMjM0NTY.SflKxwRJSMeKKF2QT4",
            "password=hunter2secret",
            "api_key: 9f8e7d6c5b4a3210",
        ]
        for raw in cases:
            self.assertIn("[REDACTED]", self.r.redact(raw), raw)

    def test_leaves_ordinary_prose_alone(self) -> None:
        text = "The quick brown fox fetched https://example.com and returned 42 rows."
        self.assertEqual(text, self.r.redact(text))

    def test_recurses_into_dicts_and_lists(self) -> None:
        payload = {
            "note": "key is sk-ant-api03-abcdefghij1234567890ABCDEFG",
            "items": ["clean", "token=supersecretvalue"],
            "n": 5,
        }
        out = self.r.redact(payload)
        self.assertIn("[REDACTED]", out["note"])
        self.assertIn("[REDACTED]", out["items"][1])
        self.assertEqual(out["items"][0], "clean")
        self.assertEqual(out["n"], 5)

    def test_field_allowlist_skips_safe_keys(self) -> None:
        # A sha-like value under an allowlisted key must be left intact.
        payload = {"system_prompt_sha256": "AKIAIOSFODNN7EXAMPLE", "body": "AKIAIOSFODNN7EXAMPLE"}
        out = self.r.redact(payload)
        self.assertEqual(out["system_prompt_sha256"], "AKIAIOSFODNN7EXAMPLE")  # untouched
        self.assertIn("[REDACTED]", out["body"])  # scrubbed

    def test_does_not_mutate_input(self) -> None:
        payload = {"x": "password=hunter2secret"}
        self.r.redact(payload)
        self.assertEqual(payload["x"], "password=hunter2secret")  # original intact


class BuildRedactorTests(unittest.TestCase):
    def test_disabled_returns_null(self) -> None:
        self.assertIsInstance(build_redactor({"Enabled": False}), NullRedactor)

    def test_default_enabled(self) -> None:
        self.assertIsInstance(build_redactor(None), RegexRedactor)
        self.assertIsInstance(build_redactor({}), RegexRedactor)

    def test_unredacted_env_overrides_config(self) -> None:
        os.environ["MICRO_X_OBSERVABILITY_UNREDACTED"] = "1"
        try:
            self.assertIsInstance(build_redactor({"Enabled": True}), NullRedactor)
        finally:
            del os.environ["MICRO_X_OBSERVABILITY_UNREDACTED"]

    def test_extra_patterns_and_allowlist(self) -> None:
        r = build_redactor({"ExtraPatterns": [r"CUSTOM-\d{4}"], "FieldAllowlist": ["keepme"]})
        out = r.redact({"a": "CUSTOM-1234", "keepme": "CUSTOM-1234"})
        self.assertIn("[REDACTED]", out["a"])
        self.assertEqual(out["keepme"], "CUSTOM-1234")


class RedactionIntegrationTests(unittest.TestCase):
    """Redaction at the real write paths (events + tool_calls audit) — not live messages."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "memory.db"))
        self.redactor = RegexRedactor()
        self.emitter = EventEmitter(self.store, redactor=self.redactor)
        self.sm = SessionManager(self.store, "m", self.emitter, redactor=self.redactor)
        self.sid = self.sm.create_session("t")

    def tearDown(self) -> None:
        self.store.close()

    def test_event_payload_redacted_in_db(self) -> None:
        self.emitter.emit(self.sid, "test.event", {"leak": "api_key=topsecret12345"})
        row = next(iter(self.store.execute("SELECT payload_json FROM events WHERE type = 'test.event'")))
        self.assertIn("[REDACTED]", row["payload_json"])
        self.assertNotIn("topsecret12345", row["payload_json"])

    def test_tool_call_audit_redacted(self) -> None:
        self.sm.record_tool_call(
            self.sid, message_id=None, tool_name="http",
            tool_input={"auth": "Bearer abcdef1234567890"},
            result_text="token=anothersecretvalue", is_error=False,
        )
        row = next(iter(self.store.execute("SELECT input_json, result_text FROM tool_calls")))
        self.assertIn("[REDACTED]", row["input_json"])
        self.assertIn("[REDACTED]", row["result_text"])

    def test_live_messages_not_redacted(self) -> None:
        """The messages table is replayed into the model — it must stay raw."""
        secret = "password=keepmereal123"
        self.sm.append_message(self.sid, "user", secret)
        loaded = self.sm.load_messages(self.sid)
        self.assertEqual(loaded[0]["content"], secret)  # NOT redacted

    def test_null_redactor_passthrough(self) -> None:
        emitter = EventEmitter(self.store, redactor=NullRedactor())
        emitter.emit(self.sid, "raw.event", {"leak": "api_key=topsecret12345"})
        row = next(iter(self.store.execute("SELECT payload_json FROM events WHERE type = 'raw.event'")))
        self.assertIn("topsecret12345", row["payload_json"])


if __name__ == "__main__":
    unittest.main()
