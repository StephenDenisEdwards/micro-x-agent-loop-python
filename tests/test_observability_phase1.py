"""Phase 1 (session step-through MVP) — schema, persistence, code/config tagging, routing rationale."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest

from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.observability import config_hash, resolve_code_sha
from micro_x_agent_loop.routing_strategy import RoutingStrategy
from micro_x_agent_loop.semantic_classifier import TaskClassification
from micro_x_agent_loop.task_taxonomy import TaskType


def _make_store() -> tuple[MemoryStore, str]:
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "memory.db")
    return MemoryStore(path), path


class SchemaTests(unittest.TestCase):
    def test_system_prompts_table_and_tool_call_columns_exist(self) -> None:
        store, _ = _make_store()
        try:
            tables = {r["name"] for r in store.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("system_prompts", tables)
            cols = {r["name"] for r in store.execute("PRAGMA table_info(tool_calls)")}
            self.assertIn("was_truncated", cols)
            self.assertIn("original_chars", cols)
        finally:
            store.close()

    def test_events_session_type_index_present(self) -> None:
        store, _ = _make_store()
        try:
            idx = {r["name"] for r in store.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_events_session_type", idx)
        finally:
            store.close()

    def test_migration_adds_columns_to_legacy_db(self) -> None:
        """A DB whose tool_calls predates the truncation columns gets them via ALTER."""
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "legacy.db")
        # Build a legacy tool_calls table without the new columns.
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE tool_calls (id TEXT PRIMARY KEY, session_id TEXT, message_id TEXT, "
            "tool_name TEXT, input_json TEXT, result_text TEXT, is_error INTEGER, created_at TEXT)"
        )
        conn.commit()
        conn.close()

        store = MemoryStore(path)  # opening runs the migration
        try:
            cols = {r["name"] for r in store.execute("PRAGMA table_info(tool_calls)")}
            self.assertIn("was_truncated", cols)
            self.assertIn("original_chars", cols)
        finally:
            store.close()


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, _ = _make_store()
        self.sm = SessionManager(self.store, "test-model", EventEmitter(self.store))
        self.session_id = self.sm.create_session("t")

    def tearDown(self) -> None:
        self.store.close()

    def test_persist_system_prompt_dedups_by_sha256(self) -> None:
        text = "you are a helpful agent"
        sha1 = self.sm.persist_system_prompt(text)
        sha2 = self.sm.persist_system_prompt(text)  # idempotent
        self.assertEqual(sha1, sha2)
        self.assertEqual(sha1, hashlib.sha256(text.encode("utf-8")).hexdigest())
        rows = list(self.store.execute("SELECT text, chars FROM system_prompts WHERE sha256 = ?", (sha1,)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], text)
        self.assertEqual(rows[0]["chars"], len(text))

    def test_record_tool_call_persists_truncation_fields(self) -> None:
        self.sm.record_tool_call(
            self.session_id,
            message_id=None,
            tool_name="web_fetch",
            tool_input={"url": "x"},
            result_text="short",
            is_error=False,
            was_truncated=True,
            original_chars=50000,
        )
        row = next(iter(self.store.execute("SELECT was_truncated, original_chars FROM tool_calls")))
        self.assertEqual(row["was_truncated"], 1)
        self.assertEqual(row["original_chars"], 50000)

    def test_record_tool_call_defaults(self) -> None:
        self.sm.record_tool_call(
            self.session_id,
            message_id=None,
            tool_name="echo",
            tool_input={},
            result_text="ok",
            is_error=False,
        )
        row = next(iter(self.store.execute("SELECT was_truncated, original_chars FROM tool_calls")))
        self.assertEqual(row["was_truncated"], 0)
        self.assertIsNone(row["original_chars"])


class CodeAndConfigTaggingTests(unittest.TestCase):
    def test_config_hash_is_stable_and_order_independent(self) -> None:
        a = config_hash({"model": "m", "temperature": 0.0})
        b = config_hash({"temperature": 0.0, "model": "m"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, config_hash({"model": "m2", "temperature": 0.0}))

    def test_code_sha_env_override(self) -> None:
        import micro_x_agent_loop.observability as obs

        obs._CODE_SHA = None
        os.environ["MICRO_X_CODE_SHA"] = "deadbeef"
        try:
            self.assertEqual(resolve_code_sha(), "deadbeef")
        finally:
            del os.environ["MICRO_X_CODE_SHA"]
            obs._CODE_SHA = None

    def test_code_sha_never_empty(self) -> None:
        import micro_x_agent_loop.observability as obs

        obs._CODE_SHA = None
        sha = resolve_code_sha()
        self.assertTrue(sha)  # a real sha, "<sha>-dirty", or "unknown"
        obs._CODE_SHA = None


class RoutingDecisionRationaleTests(unittest.IsolatedAsyncioTestCase):
    def _strategy(self, **kwargs: object) -> RoutingStrategy:
        defaults: dict = {
            "default_model": "main-model",
            "routing_fallback_provider": "anthropic",
            "routing_fallback_model": "main-model",
        }
        defaults.update(kwargs)
        return RoutingStrategy(**defaults)  # type: ignore[arg-type]

    async def test_decision_exposes_policy_rationale(self) -> None:
        def classifier(**_: object) -> TaskClassification:
            return TaskClassification(task_type=TaskType.TRIVIAL, stage="rules", confidence=0.95, reason="simple")

        strategy = self._strategy(
            semantic_classifier=classifier,
            provider_pool=_StubPool(),
            routing_policies={"trivial": {"provider": "anthropic", "model": "small", "tool_search_only": False}},
        )
        decision = await strategy.decide(
            user_message="hi",
            turn_iteration=0,
            turn_number=1,
            api_tools=[{"name": "echo"}],
            pinned_target=None,
        )
        self.assertEqual(decision.policy_name, "trivial")
        self.assertEqual(decision.reason, "simple")
        self.assertFalse(decision.confidence_gate_triggered)

    async def test_confidence_gate_flag_surfaced(self) -> None:
        def classifier(**_: object) -> TaskClassification:
            return TaskClassification(task_type=TaskType.TRIVIAL, stage="rules", confidence=0.3, reason="unsure")

        strategy = self._strategy(
            semantic_classifier=classifier,
            provider_pool=_StubPool(),
            routing_confidence_threshold=0.8,
            routing_policies={"trivial": {"provider": "ollama", "model": "small"}},
        )
        decision = await strategy.decide(
            user_message="hi",
            turn_iteration=0,
            turn_number=1,
            api_tools=[{"name": "echo"}],
            pinned_target=None,
        )
        self.assertTrue(decision.confidence_gate_triggered)
        self.assertEqual(decision.effective_model, "main-model")  # downgrade refused


class _StubPool:
    """Minimal ProviderPool stand-in for routing tests."""

    active_cache_provider = "anthropic"

    def should_switch_provider(self, *_: object, **__: object) -> bool:
        return True


if __name__ == "__main__":
    unittest.main()
