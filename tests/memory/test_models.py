"""Tests for memory data models."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.memory.models import MessageRecord, SessionRecord


class SessionRecordTests(unittest.TestCase):
    def test_create(self) -> None:
        r = SessionRecord(
            id="s1",
            parent_session_id=None,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:01:00+00:00",
            status="active",
            model="claude-3",
            metadata_json="{}",
        )
        self.assertEqual("s1", r.id)
        self.assertIsNone(r.parent_session_id)
        self.assertEqual("active", r.status)
        self.assertEqual("claude-3", r.model)

    def test_frozen(self) -> None:
        r = SessionRecord(
            id="s1",
            parent_session_id="parent",
            created_at="t",
            updated_at="t",
            status="active",
            model="m",
            metadata_json="{}",
        )
        with self.assertRaises((AttributeError, TypeError)):
            r.id = "new"  # type: ignore[misc]

    def test_equality(self) -> None:
        r1 = SessionRecord(
            id="s1",
            parent_session_id=None,
            created_at="t",
            updated_at="t",
            status="active",
            model="m",
            metadata_json="{}",
        )
        r2 = SessionRecord(
            id="s1",
            parent_session_id=None,
            created_at="t",
            updated_at="t",
            status="active",
            model="m",
            metadata_json="{}",
        )
        self.assertEqual(r1, r2)


class MessageRecordTests(unittest.TestCase):
    def test_create(self) -> None:
        m = MessageRecord(
            id="m1",
            session_id="s1",
            seq=1,
            role="user",
            content_json='[{"type": "text", "text": "hello"}]',
            created_at="2026-01-01T00:00:00+00:00",
            token_estimate=10,
        )
        self.assertEqual("m1", m.id)
        self.assertEqual("s1", m.session_id)
        self.assertEqual(1, m.seq)
        self.assertEqual("user", m.role)
        self.assertEqual(10, m.token_estimate)

    def test_frozen(self) -> None:
        m = MessageRecord(
            id="m1",
            session_id="s1",
            seq=1,
            role="user",
            content_json="[]",
            created_at="t",
            token_estimate=0,
        )
        with self.assertRaises((AttributeError, TypeError)):
            m.seq = 99  # type: ignore[misc]

    def test_equality(self) -> None:
        m1 = MessageRecord(
            id="m1",
            session_id="s1",
            seq=1,
            role="user",
            content_json="[]",
            created_at="t",
            token_estimate=5,
        )
        m2 = MessageRecord(
            id="m1",
            session_id="s1",
            seq=1,
            role="user",
            content_json="[]",
            created_at="t",
            token_estimate=5,
        )
        self.assertEqual(m1, m2)


if __name__ == "__main__":
    unittest.main()
