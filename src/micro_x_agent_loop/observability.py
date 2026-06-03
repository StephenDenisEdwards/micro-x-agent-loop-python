"""ObservabilityEmitter — the single seam every observability fact passes through.

Per ADR-026 (single event log; projections, not parallel writers): the memory
``events`` table is the source of truth; the other sinks (``metrics.jsonl``,
``routing_outcomes``) are *projections* fed from this same emit path, not
independent writers. Before this seam existed, one logical fact (e.g. "an LLM
call happened") was written three times from three unrelated code paths;
consolidating here removes that triple-write.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from typing import Protocol

from loguru import logger

Subscriber = Callable[[str, dict], None]
"""Projection sink: ``(event_type, enriched_payload) -> None``."""

_CODE_SHA: str | None = None


def resolve_code_sha() -> str:
    """Best-effort identity of the running code, computed once per process.

    Order: ``MICRO_X_CODE_SHA`` env override → ``git rev-parse HEAD`` with a
    ``-dirty`` suffix when the working tree has uncommitted changes → ``unknown``
    when neither is available (e.g. a packaged deploy with no ``.git``). The
    dirty suffix matters because step-through traces are most often read while
    actively editing the very code that produced them.
    """
    global _CODE_SHA
    if _CODE_SHA is not None:
        return _CODE_SHA
    sha = os.environ.get("MICRO_X_CODE_SHA", "").strip()
    if not sha:
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if sha:
                dirty = subprocess.run(
                    ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if dirty:
                    sha += "-dirty"
        except Exception:
            sha = ""
    _CODE_SHA = sha or "unknown"
    return _CODE_SHA


def config_hash(snapshot: dict) -> str:
    """Stable short hash of a config snapshot — tags traces to the config that drove them."""
    serialized = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class _EventLog(Protocol):
    """Minimal persistence dependency — satisfied by ``MemoryFacade``."""

    def emit_event(self, event_type: str, payload: dict) -> None: ...


class ObservabilityEmitter:
    """Single emit seam: persist once to the event log, then fan out to projections.

    ``emit`` does two things, in order:

    1. **Persist** the fact to the event log via the memory facade. This is the
       authoritative store. It is a no-op when memory is disabled
       (``NullMemoryFacade``) — projections still fire, so ``metrics.jsonl``
       keeps working without memory.
    2. **Fan out** the same enriched payload to registered subscribers, which
       write the projection sinks. A subscriber that raises never breaks the
       persist, the pipeline, or the other subscribers.

    Every payload is stamped with a ``_meta`` correlation tuple
    ``{"turn", "iter", "seq"}`` so replay can group and order the events of a
    single iteration deterministically — ``created_at`` alone collides at
    second resolution. ``seq`` is a process-monotonic counter assigned at emit
    time. ``iter`` is the agentic-loop iteration index; it is ``0`` in Phase 0
    (the per-iteration value is threaded through in Phase 1's ``llm.call`` work)
    but the field exists now so the correlation schema is stable.
    """

    def __init__(self, memory: _EventLog) -> None:
        self._memory = memory
        self._subscribers: list[Subscriber] = []
        self._seq = 0

    def subscribe(self, callback: Subscriber) -> None:
        """Register a projection sink. Called in registration order on each emit."""
        self._subscribers.append(callback)

    def emit(self, event_type: str, payload: dict, *, turn_number: int, iteration: int = 0) -> dict:
        """Emit one observability fact. Returns the enriched payload (handy for tests)."""
        self._seq += 1
        enriched = {**payload, "_meta": {"turn": turn_number, "iter": iteration, "seq": self._seq}}

        # 1. Persist to the event log — source of truth (no-op when memory off).
        try:
            self._memory.emit_event(event_type, enriched)
        except Exception as ex:
            logger.warning(f"Observability persist failed for {event_type}: {ex}")

        # 2. Fan out to projection sinks (best-effort, isolated per subscriber).
        for cb in self._subscribers:
            try:
                cb(event_type, enriched)
            except Exception as ex:
                logger.warning(f"Observability subscriber failed for {event_type}: {ex}")

        return enriched
