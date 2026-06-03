"""Cost rollups + sampling policy (PLAN-observability Phase 7).

``compute_cost_rollups`` aggregates ``metric.api_call`` events into the
``cost_rollups`` table keyed by ``(date, user_id, task_type, provider, model)``,
so cost-per-user / cost-per-task-type reports are available without scanning
every event. ``should_retain_full`` is the sampling decision (100% retention for
errors and high-cost sessions; downsample low-cost successes) — a pure function
a retention job consumes.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from micro_x_agent_loop.memory.store import MemoryStore


@dataclass(frozen=True)
class RollupRow:
    date: str
    user_id: str
    task_type: str
    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _date_of(created_at: str) -> str:
    # events store ISO-8601 (second resolution); fall back to the raw prefix.
    try:
        return datetime.fromisoformat(created_at).astimezone(UTC).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(created_at)[:10]


def compute_cost_rollups(store: MemoryStore, *, persist: bool = True) -> list[RollupRow]:
    """Aggregate ``metric.api_call`` events into per-(date,user,task,provider,model) rows.

    ``user_id`` comes from the session; ``task_type`` from the turn's
    ``routing.decision`` event (``""`` when routing wasn't used). When *persist*
    is true the rows replace the ``cost_rollups`` table.
    """
    user_by_session: dict[str, str] = {
        r["id"]: (r["user_id"] or "") for r in store.execute("SELECT id, user_id FROM sessions")
    }

    # (session_id, turn) -> task_type, from routing.decision events.
    task_by_turn: dict[tuple[str, int], str] = {}
    for r in store.execute("SELECT session_id, payload_json FROM events WHERE type = 'routing.decision'"):
        try:
            p = json.loads(r["payload_json"])
            task_by_turn[(r["session_id"], int(p.get("turn_number", 0)))] = str(p.get("task_type", ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    acc: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    for r in store.execute(
        "SELECT session_id, payload_json, created_at FROM events WHERE type = 'metric.api_call'"
    ):
        try:
            p = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        turn = int(p.get("turn_number", 0) or 0)
        key = (
            _date_of(r["created_at"]),
            user_by_session.get(r["session_id"], ""),
            task_by_turn.get((r["session_id"], turn), ""),
            str(p.get("provider", "")),
            str(p.get("model", "")),
        )
        cell = acc[key]
        cell[0] += 1
        cell[1] += int(p.get("input_tokens", 0) or 0)
        cell[2] += int(p.get("output_tokens", 0) or 0)
        cell[3] += float(p.get("estimated_cost_usd", 0) or 0)

    rows = [
        RollupRow(date, user, task, provider, model, int(c[0]), int(c[1]), int(c[2]), float(c[3]))
        for (date, user, task, provider, model), c in sorted(acc.items())
    ]

    if persist and rows:
        with store.transaction():
            store.execute("DELETE FROM cost_rollups")
            store.executemany(
                "INSERT INTO cost_rollups "
                "(date, user_id, task_type, provider, model, calls, input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (r.date, r.user_id, r.task_type, r.provider, r.model, r.calls,
                     r.input_tokens, r.output_tokens, r.cost_usd)
                    for r in rows
                ],
            )
    return rows


def should_retain_full(cost_usd: float, had_error: bool, *, low_cost_threshold: float = 0.01) -> bool:
    """Sampling decision: keep full detail for errors and non-trivial-cost sessions.

    Low-cost *successful* sessions are the only ones eligible for downsampling
    (caller decides the downsample fraction); everything else is retained 100%.
    """
    if had_error:
        return True
    return cost_usd >= low_cost_threshold
