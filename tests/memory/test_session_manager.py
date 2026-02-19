from tests.memory.base import MemoryStoreTestCase


class SessionManagerTests(MemoryStoreTestCase):
    def test_sessions_have_default_title(self) -> None:
        sid = self._sessions.create_session("with-title")
        session = self._sessions.get_session(sid)
        self.assertIsNotNone(session)
        self.assertIn("title", session)
        self.assertTrue(str(session["title"]).startswith("Session "))

    def test_set_session_title_updates_metadata(self) -> None:
        sid = self._sessions.create_session("rename-me")
        self._sessions.set_session_title(sid, "Interview Prep - Morning")
        session = self._sessions.get_session(sid)
        self.assertIsNotNone(session)
        self.assertEqual("Interview Prep - Morning", session["title"])

    def test_resolve_session_identifier_by_id_and_title(self) -> None:
        sid = self._sessions.create_session("resolve-id", title="Daily Standup")
        by_id = self._sessions.resolve_session_identifier("resolve-id")
        by_title = self._sessions.resolve_session_identifier("daily standup")
        self.assertIsNotNone(by_id)
        self.assertIsNotNone(by_title)
        self.assertEqual(sid, by_id["id"])
        self.assertEqual(sid, by_title["id"])

    def test_resolve_session_identifier_raises_when_ambiguous(self) -> None:
        self._sessions.create_session("a1", title="Duplicate Name")
        self._sessions.create_session("a2", title="Duplicate Name")
        with self.assertRaises(ValueError):
            self._sessions.resolve_session_identifier("Duplicate Name")

    def test_create_append_and_load_messages(self) -> None:
        sid = self._sessions.create_session("s-test")
        self._sessions.append_message(sid, "user", "hello")
        self._sessions.append_message(sid, "assistant", [{"type": "text", "text": "world"}])

        loaded = self._sessions.load_messages(sid)
        self.assertEqual(2, len(loaded))
        self.assertEqual("user", loaded[0]["role"])
        self.assertEqual("hello", loaded[0]["content"])
        self.assertEqual("assistant", loaded[1]["role"])

    def test_load_or_create_is_idempotent(self) -> None:
        sid = self._sessions.load_or_create("stable-id")
        same_sid = self._sessions.load_or_create("stable-id")
        self.assertEqual("stable-id", sid)
        self.assertEqual("stable-id", same_sid)
        rows = self._store.execute("SELECT COUNT(*) AS c FROM sessions WHERE id = ?", ("stable-id",)).fetchone()
        self.assertEqual(1, int(rows["c"]))

    def test_record_tool_call_persists(self) -> None:
        sid = self._sessions.create_session("s-tools")
        msg_id, _ = self._sessions.append_message(
            sid,
            "assistant",
            [{"type": "tool_use", "id": "x", "name": "read_file", "input": {}}],
        )
        self._sessions.record_tool_call(
            sid,
            message_id=msg_id,
            tool_name="read_file",
            tool_input={"path": "a.txt"},
            result_text="ok",
            is_error=False,
            tool_call_id="call-1",
        )
        row = self._store.execute("SELECT * FROM tool_calls WHERE id = 'call-1'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual("read_file", row["tool_name"])
        self.assertEqual(0, row["is_error"])

    def test_fork_copies_transcript_and_sets_parent(self) -> None:
        sid = self._sessions.create_session("parent-session")
        self._sessions.append_message(sid, "user", "u1")
        self._sessions.append_message(sid, "assistant", [{"type": "text", "text": "a1"}])

        fork_id = self._sessions.fork_session(sid, "child-session")
        self.assertEqual("child-session", fork_id)

        parent_row = self._sessions.get_session(fork_id)
        self.assertIsNotNone(parent_row)
        self.assertEqual("parent-session", parent_row["parent_session_id"])
        self.assertIn("Fork of", parent_row["title"])

        parent_msgs = self._sessions.load_messages(sid)
        child_msgs = self._sessions.load_messages(fork_id)
        self.assertEqual(parent_msgs, child_msgs)

    def test_list_sessions_returns_recent_first_with_limit(self) -> None:
        self._sessions.create_session("s1")
        self._sessions.create_session("s2")
        self._sessions.create_session("s3")
        self._store.execute("UPDATE sessions SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = 's1'")
        self._store.execute("UPDATE sessions SET updated_at = '2021-01-01T00:00:00+00:00' WHERE id = 's2'")
        self._store.execute("UPDATE sessions SET updated_at = '2022-01-01T00:00:00+00:00' WHERE id = 's3'")
        self._store.commit()

        sessions = self._sessions.list_sessions(limit=2)
        ids = [s["id"] for s in sessions]
        self.assertEqual(["s3", "s2"], ids)

    def test_build_session_summary_includes_counts_and_previews(self) -> None:
        sid = self._sessions.create_session("summary")
        self._sessions.append_message(sid, "user", "First user message")
        self._sessions.append_message(sid, "assistant", [{"type": "text", "text": "Assistant answer"}])
        self._sessions.append_message(sid, "user", "Second user message for preview")

        summary = self._sessions.build_session_summary(sid)
        self.assertEqual("summary", summary["session_id"])
        self.assertEqual(3, summary["message_count"])
        self.assertEqual(2, summary["user_message_count"])
        self.assertEqual(1, summary["assistant_message_count"])
        self.assertEqual(0, summary["checkpoint_count"])
        self.assertIn("Second user message", summary["last_user_preview"])
        self.assertIn("Assistant answer", summary["last_assistant_preview"])
