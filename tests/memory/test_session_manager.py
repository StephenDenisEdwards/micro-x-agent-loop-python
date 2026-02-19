from tests.memory.base import MemoryStoreTestCase


class SessionManagerTests(MemoryStoreTestCase):
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
