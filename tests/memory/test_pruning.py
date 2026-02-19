from tests.memory.base import MemoryStoreTestCase
from micro_x_agent_loop.memory import prune_memory


class PruningTests(MemoryStoreTestCase):
    def test_retention_days_prunes_old_sessions(self) -> None:
        old_sid = self._sessions.create_session("old")
        self._sessions.append_message(old_sid, "user", "old message")
        self._store.execute("UPDATE sessions SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = 'old'")
        self._store.commit()

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=5000,
            retention_days=1,
        )

        row = self._store.execute("SELECT id FROM sessions WHERE id = 'old'").fetchone()
        self.assertIsNone(row)

    def test_max_messages_per_session_keeps_latest(self) -> None:
        sid = self._sessions.create_session("msg-cap")
        for i in range(5):
            self._sessions.append_message(sid, "user", f"m{i}")

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=2,
            retention_days=36500,
        )

        rows = self._store.execute(
            "SELECT seq, content_json FROM messages WHERE session_id = ? ORDER BY seq ASC",
            (sid,),
        ).fetchall()
        self.assertEqual(2, len(rows))
        self.assertEqual(4, int(rows[0]["seq"]))
        self.assertEqual(5, int(rows[1]["seq"]))

    def test_max_sessions_keeps_most_recent(self) -> None:
        self._sessions.create_session("s1")
        self._sessions.create_session("s2")
        self._sessions.create_session("s3")
        self._store.execute("UPDATE sessions SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = 's1'")
        self._store.execute("UPDATE sessions SET updated_at = '2021-01-01T00:00:00+00:00' WHERE id = 's2'")
        self._store.execute("UPDATE sessions SET updated_at = '2022-01-01T00:00:00+00:00' WHERE id = 's3'")
        self._store.commit()

        prune_memory(
            self._store,
            max_sessions=2,
            max_messages_per_session=5000,
            retention_days=36500,
        )

        rows = self._store.execute("SELECT id FROM sessions ORDER BY id ASC").fetchall()
        ids = [str(r["id"]) for r in rows]
        self.assertEqual(["s2", "s3"], ids)
