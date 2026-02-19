from __future__ import annotations

from datetime import UTC, datetime, timedelta

from micro_x_agent_loop.memory.store import MemoryStore


def prune_memory(
    store: MemoryStore,
    *,
    max_sessions: int,
    max_messages_per_session: int,
    retention_days: int,
) -> None:
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=max(1, retention_days))).isoformat(timespec="seconds")

    store.execute(
        "DELETE FROM sessions WHERE updated_at < ?",
        (cutoff,),
    )

    if max_messages_per_session > 0:
        sessions = store.execute("SELECT id FROM sessions").fetchall()
        for session_row in sessions:
            session_id = str(session_row["id"])
            overflow = store.execute(
                """
                SELECT id
                FROM messages
                WHERE session_id = ?
                ORDER BY seq DESC
                LIMIT -1 OFFSET ?
                """,
                (session_id, max_messages_per_session),
            ).fetchall()
            if overflow:
                store.executemany(
                    "DELETE FROM messages WHERE id = ?",
                    [(str(row["id"]),) for row in overflow],
                )

    if max_sessions > 0:
        overflow_sessions = store.execute(
            """
            SELECT id
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT -1 OFFSET ?
            """,
            (max_sessions,),
        ).fetchall()
        if overflow_sessions:
            store.executemany(
                "DELETE FROM sessions WHERE id = ?",
                [(str(row["id"]),) for row in overflow_sessions],
            )

    store.commit()
