"""ObservabilityEmitter — the single seam every observability fact passes through.

Per ADR-026 (single event log; projections, not parallel writers): the memory
``events`` table is the source of truth; the other sinks (``metrics.jsonl``,
``routing_outcomes``) are *projections* fed from this same emit path, not
independent writers. Before this seam existed, one logical fact (e.g. "an LLM
call happened") was written three times from three unrelated code paths;
consolidating here removes that triple-write.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from loguru import logger

Subscriber = Callable[[str, dict], None]
"""Projection sink: ``(event_type, enriched_payload) -> None``."""


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
