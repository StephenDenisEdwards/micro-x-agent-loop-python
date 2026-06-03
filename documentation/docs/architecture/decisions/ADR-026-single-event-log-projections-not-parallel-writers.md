# ADR-026: Single Event Log as Source of Truth; Other Sinks Are Projections

## Status

Accepted — 2026-06-03. Implemented as Phase 0 of [PLAN-observability.md](../../planning/PLAN-observability.md): `observability.py` (`ObservabilityEmitter`), `metrics.metrics_jsonl_subscriber`, `routing_feedback.make_routing_outcome_subscriber`, the `idx_events_session_type` index, and the removal of the triple-write in `agent.py`.

## Context

Observability data lands in five sinks today:

| Sink | Contents | Write path |
|---|---|---|
| `.micro_x/memory.db` — `events` table | generic `(type, payload_json)` event log | `EventEmitter.emit` / `AsyncEventSink` |
| `.micro_x/memory.db` — `sessions`/`messages`/`tool_calls` | conversation history | `SessionManager` (sync) |
| `.micro_x/routing_feedback.db` — `routing_outcomes` | per-call task_type, model, cost, latency, confidence | `RoutingFeedbackStore.record` (sync) |
| `metrics.jsonl` | `metric.*` records (api_call, tool_execution, compaction, session_summary) | `emit_metric` → loguru |
| `api_payloads.jsonl` + in-memory `ApiPayloadStore` | full prompts + completions (ring of 50; JSONL only at DEBUG) | `TurnEngine._record_api_payload` |

An audit of the write paths (2026-06-02) found that the framing "data lands in five places" understates the real issue. The problem is not five *locations* — it is **three parallel emit abstractions that record the same facts independently**, fanned out from a single method.

### The triple-write

From one `Agent.on_api_call_completed()` (agent.py:690-708) plus the routing-feedback callback wired in `Agent.__init__` (agent.py:298-310), a single logical "an LLM call happened" fact is written three times, through three unrelated code paths:

| Path | Sink | Carries |
|---|---|---|
| `emit_metric(build_api_call_metric(...))` (agent.py:707) | `metrics.jsonl` via loguru | session, turn, model, provider, cost, latency, tokens |
| `_memory.emit_event("metric.api_call", metric)` (agent.py:708) | `memory.db` `events` table | the *same dict, verbatim* |
| `RoutingFeedbackStore.record(...)` (routing_feedback.py:70-92) | `routing_feedback.db` | session, turn, task_type, model, provider, cost, latency, confidence, stage |

`session_id`, `turn_number`, `model`, `provider`, `cost_usd`, and `latency_ms` are written to all three with no shared source of truth. There are **three distinct emit abstractions** — the generic `EventEmitter`, the loguru-backed `emit_metric`, and the bespoke `RoutingFeedbackStore` — and no single seam through which "one fact" passes once.

### What is already right

The audit also found that the load-bearing pieces of a clean design already exist:

- **The `events` table is already a generic event log** — `(id, session_id, type, payload_json, created_at)` with no enum constraint on `type` (store.py:102-108). New event types need no migration.
- **`SessionAccumulator` already reconstructs session state by replaying `metric.*` events** from that table (metrics.py:276-346). An event-sourcing substrate is already in place — it is simply not the *single* source of truth.
- **Instrumentation is ~80% cleanly injected** through the `TurnEvents` protocol (turn_events.py; held by `TurnEngine` as `self._events`) and the `AgentChannel`. The seams a unified emitter needs are already there.
- **The provider layer is clean** — `anthropic`/`openai`/`ollama` providers return `UsageResult` and let callers decide what to record. No telemetry is hardcoded into the hot path.

### Why this matters now

[PLAN-observability.md](../../planning/PLAN-observability.md) adds `llm.call`, `routing.decision`, `mode.analyzed`, and `session.config` events in Phase 1, then `/replay` (Phase 2) reads them from `memory.db`, while alerting (Phase 5) is specified against `metrics.jsonl`, and routing analytics live in `routing_feedback.db`. Built as planned, replay, alerting, and routing analytics would each sit on a *different* substrate — deepening the existing divergence across seven phases. The multi-tenant phases compound it: PII redaction (Phase 3) and `user_id` cost rollups (Phase 7) each become three times the work, once per write path.

A full re-architecture is **not** warranted — the seams and the generic event log already exist, the provider boundary is clean, and a rewrite would re-derive what is there at high regression risk on a working system. The right scope is a bounded consolidation, done once, before new event types are added.

## Decision

**The `memory.db` `events` table is the single source of truth for observability facts. Every observability fact is emitted exactly once, through one seam. `metrics.jsonl` and `routing_feedback.db` become projections derived from that emit path — not independent writers.**

Concretely:

### Rule 1 — One emit seam

All observability facts flow through a single `ObservabilityEmitter` seam. This extends the existing `TurnEvents` protocol rather than introducing new plumbing — `TurnEngine` already routes turn-level instrumentation through `self._events`, and the provider layer already returns data for callers to record. Business logic emits a fact once; it does not call `emit_metric`, `emit_event`, and `RoutingFeedbackStore.record` in sequence for the same fact.

### Rule 2 — The event log is authoritative

A fact is persisted to the `events` table once, with a stable correlation key (see Rule 4). Anything downstream that needs that fact reads or derives it from the event log.

### Rule 3 — Other sinks are projections, not parallel writers

- `metrics.jsonl` is produced by a consumer/exporter subscribed to the emit path (the loguru sink stays as an *output* of the unified stream, not an independent `emit_metric` call site). It remains the on-disk analytics log; it is no longer a second authority.
- `routing_feedback.db` is a projection of `routing.decision` events — either a derived view/consumer, or the same table written from the unified emit path, never a separate callback closure recording facts the event log does not have.
- The verbatim double-write at agent.py:707-708 is removed: the metric dict is persisted once, and `metrics.jsonl` is derived from it.

### Rule 4 — Correlation key on every observability event

Every observability event carries a stable `(turn_number, iteration, seq)` correlation tuple, not just `created_at`. Ordering by timestamp is insufficient — async emits within a single iteration collide at timestamp resolution, and replay must line up the mode decision, routing decision, and LLM call that belong to the same iteration. (This folds in the turn-correlation gap identified in the Phase 1 review.)

### Rule 5 — Index the event log for replay

The `events` table carries an index on `(session_id, type)` (and the correlation ordering key). Replay and projection queries filter by session and type; without the index they table-scan. (This folds in the events-index gap identified in the Phase 1 review.)

### Scope boundary

Phase 0 consolidates the **write path**, not the schema. The six existing tables stay; `routing_feedback.db` and `metrics.jsonl` stay as files. What changes is *authority*: the event log becomes the one place a fact is recorded, and the other sinks are fed from it. This refines — does not contradict — the plan's "extend the current schema, not replace it" stance: no schema is replaced; the redundant *writers* are.

## Consequences

### Positive

- **One place to add an event type.** Phase 1's `llm.call` / `routing.decision` / `mode.analyzed` / `session.config` events, and every later phase, target one emit seam. Replay (Phase 2), alerting (Phase 5), and routing analytics all read from or derive off the same log.
- **Redaction and rollups are done once.** PII redaction (Phase 3) applies at the single emit seam instead of three write paths. `user_id` cost rollups (Phase 7) aggregate one authoritative store.
- **No drift between sinks.** The metric in `metrics.jsonl` and the metric in the `events` table can no longer disagree, because one is derived from the other rather than independently constructed.
- **Cheaper multi-tenant story.** The "single source of truth" the plan's multi-tenant goals need exists after a days-scale consolidation, not a weeks-scale rewrite.
- **Correlation makes replay deterministic.** Rule 4 means turn-by-turn reconstruction lines up events by construction, not by timestamp luck.

### Negative

- **One refactor ahead of feature work.** Phase 0 must land before Phase 1, delaying the first user-visible `/replay` value by the consolidation window. The mitigation is that Phase 1 onward is strictly cheaper afterward.
- **Routing-feedback path changes.** `RoutingFeedbackStore`'s direct callback (agent.py:298-310) is re-pointed at the unified emit path. Existing `routing_outcomes` consumers (the offline eval harness, `quality_signal` updates) must read the projection, which must preserve the current table shape.
- **The loguru metrics sink is demoted.** `emit_metric` callers (agent.py:707, 768, 782, 961) are rerouted through the emitter. The loguru handler that writes `metrics.jsonl` stays, but as a subscriber, which is a behavioural change for anything that imported `emit_metric` directly.

### Open / deferred

- **OTel as the internal spine — rejected.** Making OpenTelemetry the internal bus (emit spans natively, project to SQLite/JSONL via span processors) was considered as the genuinely "larger re-architecture" option. Rejected: it couples the core loop to the OTel SDK data model and lifecycle, it is heavyweight for the default local/single-user CLI case, and the domain-specific `TurnEvents` protocol is a cleaner seam than generic spans for this project's replay needs. OTel stays an **export projection** (plan Phase 4) hanging off the unified event log — strictly better than making it the source of truth.
- **`api_payloads.jsonl` / `ApiPayloadStore`** are left as-is by Phase 0. Persisting exact prompts to a deduped `system_prompts` table is Phase 1 work; whether the in-memory ring is then retired is deferred to that phase.
- **Backfill of historical sinks** is out of scope. Phase 0 changes the write path going forward; existing `metrics.jsonl` / `routing_feedback.db` rows are not reconciled against the event log.

## References

- [PLAN-observability.md](../../planning/PLAN-observability.md) — Phase 0 inserted by this ADR; Phases 1-7 build on the unified emit path.
- [DESIGN-cost-metrics.md](../../design/DESIGN-cost-metrics.md) — existing metrics design and `SessionAccumulator` replay (metrics.py:276-346) this ADR generalises.
- [DESIGN-memory-system.md](../../design/DESIGN-memory-system.md) — `events` table and `EventEmitter`/`AsyncEventSink` write paths.
- Audit (this ADR's session) — triple-write at agent.py:707-708 + routing callback agent.py:298-310; generic `events` schema store.py:102-108; unpopulated `routing_rule`/`routing_reason` slots metrics.py:27-28,49-51.
