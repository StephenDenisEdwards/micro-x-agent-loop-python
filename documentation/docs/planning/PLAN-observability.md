# Plan: Production-Grade Observability and Session Step-Through

## Status

**In Progress** — Drafted 2026-06-02 from audit of current state. **Phases 0–3 implemented 2026-06-03**: Phase 0 (emit-path consolidation, [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md)), Phase 1 (session step-through MVP), Phase 2 (`/replay` command), Phase 3 (PII/secret redaction). Phases 4–7 still Planned. Deferred within their phases: Anthropic `thinking` capture (Phase 1), bespoke TUI trace-view panel (Phase 2), per-table retention (Phase 3). See [observability-for-ai-agents.md](../best-practice/observability-for-ai-agents.md) for the framework this plan is measured against.

## Goals

Two outcomes drive this plan; each phase below maps to one or both.

1. **Production-grade observability.** Traces, metrics, evals, cost tracking, alerting, PII redaction, retention, and version tagging — at a quality bar suitable for a multi-tenant service.
2. **Session step-through.** For any historical session, reconstruct turn-by-turn: the exact LLM input (system prompt, message history, tools exposed), the exact LLM output (text + tool_use + thinking), each tool call's args and result, every agent decision (mode classification, routing policy applied, sub-agent spawn, compaction trigger), and the config values that drove each decision.

## Problem

Data lands today in five places and was not designed for replay:

| Sink | Contents |
|---|---|
| `.micro_x/memory.db` | sessions, messages, tool_calls, events, checkpoints |
| `.micro_x/routing_feedback.db` | per-call task_type, model, cost, latency, confidence |
| `metrics.jsonl` | structured `metric.*` events (api_call, tool_execution, compaction, session_summary) |
| `api_payloads.jsonl` | full prompts + completions — only when the DEBUG `api_payload` consumer is wired in |
| in-memory `ApiPayloadStore` | last 50 prompts + completions; lost on process restart |

**The deeper issue is not five locations — it is three parallel emit abstractions recording the same facts independently.** From a single `Agent.on_api_call_completed()` (agent.py:690-708) plus the routing-feedback callback (agent.py:298-310), one logical "an LLM call happened" fact is written three ways: `emit_metric(...)` → `metrics.jsonl`, `_memory.emit_event("metric.api_call", ...)` → the `events` table (the *same dict, verbatim*, agent.py:707-708), and `RoutingFeedbackStore.record(...)` → `routing_feedback.db`. `session_id`, `model`, `provider`, `cost_usd`, and `latency_ms` land in all three with no shared source of truth. The good news: the `events` table is already a generic `(type, payload_json)` log, `SessionAccumulator` already reconstructs state by replaying `metric.*` events (metrics.py:276-346), and instrumentation is ~80% cleanly injected through the `TurnEvents` protocol — so consolidating the write path is a bounded refactor, not a rewrite. See [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md), delivered as **Phase 0** below.

Per turn the code already captures: token counts (in/out/cache_read/cache_create), cost, latency (`duration_ms`, `time_to_first_token_ms`), model + provider, `call_type` discriminator (`main`/`semantic:<task>`/`pinned:<…>`/`subagent:<type>`/`stage2_classification`/`tool_summarization`/`nested:<tool>`), tool input verbatim, tool output (post-truncation), checkpoint scope, sub-agent completion summary, compaction stats, session lifecycle events. See [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) for the existing metrics design.

### What's blocking session step-through today

Data exists at runtime but is not persisted. Each item below is a concrete field that needs to land in a persisted store:

1. **Exact system prompt per call.** Resolved in `turn_engine.py` but only flows to in-memory `ApiPayloadStore` and the optional `api_payloads.jsonl` log.
2. **Exact tools list per call.** Only `tools_count` (integer) is stored. With tool_search narrowing, `tool_search_only` policy, and ask_user / spawn_subagent / task tool injection, the effective set differs per call.
3. **Mode-classification trace.** Stage 1 signals, Stage 2 LLM reasoning, and user choice are computed but printed — not persisted.
4. **Routing decision rationale on the LLM call.** `metrics.py`'s `routing_rule` / `routing_reason` slots exist but are never populated. We know `call_type` but not *which policy fired, whether the confidence gate refused a downgrade, whether pin-continuation latched, whether `tool_search_only` / `compact` prompt applied*.
5. **Sampling params** (`temperature`, `max_tokens`) per call — static on `TurnEngine` init but never copied into events.
6. **Anthropic `thinking` blocks.** Provider matches only `text` and `tool_use`, drops thinking.
7. **Pre-truncation tool output.** `tool_calls.result_text` stores what the LLM saw, not what the MCP server returned.
8. **Config / code versioning.** No `config_hash`, `prompt_version`, or `code_sha` tags on sessions or events.

No `/replay` or trace-view command exists. `/cost`, `/session`, and `/checkpoint` show aggregates and scope, not a turn-by-turn timeline.

### Production-grade gaps

**P0 (do first):**

- **No PII / secret redaction** anywhere on the persistence path. Tool args, results, messages, payloads all stored raw.
- **No OpenTelemetry export.** Everything is local SQLite + JSONL — can't ship to Langfuse / Phoenix / Datadog without wiring.
- **No alerting.** Single budget warning at 80% and hard cutoff at 100% — nothing for error-rate, classifier-confidence drift, cache-hit drop, turn-cap trips.
- **No config / code versioning.** Historical traces cannot be interpreted against today's code.

**P1:**

- Mode + routing decisions not persisted as events.
- Online eval harness absent. `tests/evals/` has an offline harness; `routing_outcomes.quality_signal` column declared but never written.
- No user feedback (`/feedback +1|-1`) capture.

**P2:**

- Coarse retention — whole-session pruning, no per-event policy, no separate retention for prompts vs metrics.
- No per-user / per-task-type cost rollups (`SessionAccumulator.model_subtotals` exists; no user dimension at all).
- 100% capture, no sampling.

## Phased delivery

Phases sequence smallest-surface-area first. Each phase is independently shippable. Phase 0 is a prerequisite consolidation; Phases 1-7 build on the seam it establishes.

### Phase 0 — Unify the emit path (prerequisite) — **Implemented 2026-06-03**

Per [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md). Without this, every phase below pours new event types into a write path that already records the same facts three ways — and replay (Phase 2), alerting (Phase 5), and routing analytics would each sit on a different substrate. Done once here, the rest of the plan gets strictly cheaper.

- ✅ Introduced one `ObservabilityEmitter` seam (`src/micro_x_agent_loop/observability.py`). Every observability fact is emitted exactly once through it; it persists to the event log then fans out to projection subscribers. Held by `Agent` and constructed independently of memory, so projections (e.g. `metrics.jsonl`) keep working when memory is disabled.
- ✅ Made the `memory.db` `events` table the single source of truth. Removed the verbatim double-write in `agent.py` (was `emit_metric(...)` **and** `emit_event("metric.*", ...)` for the same dict) — each metric is now emitted once.
- ✅ Turned `metrics.jsonl` into a projection: `metrics.metrics_jsonl_subscriber` writes `metric.*` events to the existing loguru sink, replacing the direct `emit_metric` call sites in `agent.py` (api_call, api_call_error, tool_execution, compaction, session_summary). `tool_execution` now also lands in the event log (it previously bypassed it), which activates the dormant `SessionAccumulator.restore_from_events` tool branch.
- ✅ Turned `routing_feedback.db` into a projection of `routing.decision` events: the routing callback emits onto the seam, and `routing_feedback.make_routing_outcome_subscriber` persists `routing_outcomes` — preserving the table shape so the offline eval harness and `quality_signal` updates keep working.
- ✅ Stamp every emitted event with a `_meta` `{turn, iter, seq}` correlation tuple (`seq` process-monotonic), so replay can group/order the events of one iteration deterministically rather than relying on second-resolution `created_at`. (Folds in the turn-correlation gap from the Phase 1 review.) **Note:** `iter` is `0` in Phase 0 — the real per-iteration index is threaded through in Phase 1's `llm.call` work; the field exists now so the schema is stable.
- ✅ Added `idx_events_session_type` on `events(session_id, type)` (alongside the existing `idx_events_session_created`), so replay and projection queries — e.g. `cost_reconciliation`'s `WHERE type = 'metric.api_call'` — don't table-scan. (Folds in the events-index gap from the Phase 1 review.)

**Scope boundary (as built):** `metric.*` and `routing.decision` — the facts that were triple-written — now flow through the seam. The remaining single-write lifecycle events (`tool.started`/`tool.completed`/`subagent.completed`/`checkpoint.*`) still go straight to the facade and do not yet carry `_meta`; migrating them to the seam is a fast-follow and was kept out of Phase 0 to keep the change focused on eliminating the triple-write.

**Acceptance (met):** a single `emit` results in all derived sinks (event log + subscribed projections); no business-logic method writes the same fact to two stores; `metrics.jsonl` and `routing_outcomes` rows are reproducible from the `events` table. Existing consumers (CLI `/cost` via `SessionAccumulator`, `cost_reconciliation`, offline eval harness) are unchanged. Covered by `tests/test_observability.py` (persist-once + fan-out, `_meta`/seq monotonicity, memory-off fan-out, subscriber-exception isolation, routing projection); full suite green (1780 passed; 3 pre-existing unrelated failures).

### Phase 1 — Session step-through MVP — **Implemented 2026-06-03**

Unblocks goal 2 with minimal new schema. Targets the Phase 0 emit seam — every event below is emitted once and flows to the event log (and any subscribed projection) through it.

- ✅ Emit `llm.call` event before each provider dispatch via a new `TurnEvents.on_llm_call` hook (turn_engine emits; `Agent` persists + emits through `self._obs`). Fields: `turn_iteration` (the real per-iteration index, carried in `_meta.iter`), `call_type`, `effective_provider`, `effective_model`, `temperature`, `max_tokens`, `message_count`, `tool_names: list[str]`, `system_prompt_sha256`, `system_prompt_chars`, `routing_rule`, `routing_reason`.
- ✅ Persist system prompts in a deduped `system_prompts(sha256 PK, text, chars, created_at)` table (`SessionManager.persist_system_prompt`, `INSERT OR IGNORE`). The `llm.call` event carries only the hash + char count, keeping event payloads small.
- ✅ Enriched the existing `routing.decision` event (Phase 0) with the rationale fields: `reason`, `policy_name`, `tool_search_only`, `system_prompt_compact`, `pin_continuation_latched`, `confidence_gate_triggered` — surfaced from `RoutingDecision` (and `_resolve_routing_target` now reports the confidence-gate trigger). Cost/latency stay on the event so the `routing_outcomes` projection is unchanged.
- ✅ Emit `mode.analyzed` event in `agent.py` per turn. Fields: `signals` (name/strength/matched_text), `stage1_recommendation`, `stage2_recommendation`, `stage2_reasoning`, `user_choice`.
- ✅ Emit `session.config` event once per session — curated scalar config snapshot + `code_sha` (env override → `git rev-parse HEAD` with a `-dirty` suffix when the tree is dirty → `unknown`) + `config_hash` (`observability.resolve_code_sha` / `config_hash`).
- ✅ Surface `was_truncated` and `original_chars` on `tool_calls` rows (schema columns + idempotent `ALTER TABLE` migration for legacy DBs; threaded from `turn_engine`'s truncation site through `on_record_tool_call`).
- ⏸️ **Deferred (within Phase 1): capture Anthropic `thinking` blocks.** Extended thinking is not enabled on the provider requests today, so there are no `thinking` blocks to capture — the change would touch the streaming hot path for zero current payload. Revisit when extended thinking is turned on.

**Acceptance (met, except deferred thinking):** given any `session_id`, a script can query `memory.db` and reconstruct turn-by-turn (a) prompt (`system_prompts` via `llm.call.system_prompt_sha256`) + tools (`tool_names`) + sampling params, (b) the response (`messages`), (c) tools run with args/results (`tool_calls`, now incl. truncation), (d) mode/routing decisions and why (`mode.analyzed`, enriched `routing.decision`), and the config that drove them (`session.config`). Events correlate via `_meta {turn, iter, seq}`. Covered by `tests/test_observability_phase1.py` (schema + legacy migration, prompt dedup, truncation round-trip, code_sha/config_hash, routing rationale incl. confidence gate). No reliance on `api_payloads.jsonl` or the in-memory ring.

### Phase 2 — `/replay` command — **Implemented 2026-06-03**

Surfaces the data from Phase 1.

- ✅ New `/replay [session_id]` slash command (REPL **and** TUI — output renders through the channel, so it works in both; defaults to the active session). Registered via `CommandRouter.on_replay` → `CommandHandler.handle_replay`; help text + TUI command-palette entries added.
- ✅ Reconstruction lives in a pure, testable module — `session_replay.reconstruct_session(store, session_id) -> list[str]` (mirrors `cost_reconciliation`). It merges the `events` log (turn-tagged via `_meta.turn`), `messages`, and `tool_calls` into one chronological stream and renders a turn-by-turn timeline: `session.config` → per turn `mode.analyzed` → `routing.decision` (incl. confidence-gate / pin / tool-search / compact flags) → `llm.call` (provider/model, sampling params, system-prompt hash+chars, tool names) → `metric.api_call` → tool calls (input/result previews, `was_truncated` with `original_chars→chars`) → compaction → assistant/user message lines. This module is also the standalone "script can query memory.db" realisation from the Phase 1 acceptance.
- ⏸️ **Deferred (within Phase 2): dedicated TUI "trace view" panel.** `/replay` already renders the full timeline as text in the TUI chat log; a bespoke side-panel widget is polish, not needed for the acceptance.
- `thinking` blocks are absent from the render because Phase 1 deferred their capture (extended thinking not enabled).

**Acceptance (met):** `/replay <session_id>` produces a complete turn-by-turn view; an engineer debugging a regression can identify the offending decision (mode/routing/llm.call/tool truncation) without leaving the agent. Covered by `tests/test_session_replay.py` (timeline render over a seeded store, confidence-gate flag, unknown-session error) and `tests/test_command_router.py::test_replay` (dispatch, and that `/replay` does not collide with `/cost`).

### Phase 3 — PII redaction and access control — **Implemented 2026-06-03**

- ✅ Pluggable `Redactor` (`src/micro_x_agent_loop/redaction.py`): `RegexRedactor` recursively scrubs str/dict/list structures; `NullRedactor` passes through. Applied at `EventEmitter.emit` (all events, before any sink/projection) and in `SessionManager` for the `tool_calls` audit record and the `system_prompts` body.
- ✅ Default redactor: high-signal regex set (Anthropic/OpenAI/Google/GitHub/Slack keys, AWS access keys, JWTs, bearer tokens, `secret|password|api_key|token=…` assignments) + a **field allowlist** (`sha256`, `model`, `provider`, `_meta`, …) so safe structural fields aren't mangled. Driven by the `ObservabilityRedaction` config block (`Enabled`, `ExtraPatterns`, `FieldAllowlist`) in `config-base.json`, parsed onto `AppConfig.observability_redaction` and built in `bootstrap`.
- ✅ "Unredacted debug mode": `MICRO_X_OBSERVABILITY_UNREDACTED=1` forces a `NullRedactor` regardless of config, for incident-response capture.
- 🔑 **Design correction (important):** redaction covers the *observability copies* — the `events` log, the `tool_calls` audit record, and `system_prompts` — but **NOT** the live `messages` table. `messages` is the working conversation replayed into the model on resume; scrubbing it would feed the model `[REDACTED]` and corrupt the session. The secret still appears once in the live `messages` row (raw, needed for replay) and is redacted in every observability copy. True multi-tenant message redaction needs a separate export pipeline (future).
- ⏸️ **Deferred (within Phase 3): per-table retention** (prompts ≤ 30d, metrics ≤ 180d, events ≤ 365d). The existing whole-session pruning (`prune_memory`) still applies; granular per-table retention is a follow-up.

**Acceptance (met):** tool args/results and event payloads containing known secrets land in the DB redacted; live `messages` stay raw (so replay is faithful); `MICRO_X_OBSERVABILITY_UNREDACTED=1` flips behaviour. Covered by `tests/test_redaction.py` (pattern set, allowlist, recursion, no-mutation, build/env-flag, and integration over real `EventEmitter`/`tool_calls`/`messages` write paths).

### Phase 4 — OpenTelemetry exporter

- Optional dependency, opt-in via config (`OtelEnabled`, `OtelEndpoint`).
- One span per session (root), child spans per turn, child spans per LLM call (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, etc. per the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)) and per tool call.
- Maps cleanly from existing `metric.api_call` and `metric.tool_execution` events.

**Acceptance:** with `OtelEnabled=true` and a Langfuse / Phoenix endpoint, sessions appear as traces with full LLM and tool spans.

### Phase 5 — Alerting

- Rolling-window thresholds computed from `metrics.jsonl` (or DuckDB-over-JSONL) — cost p99, error rate, classifier confidence average, cache-hit rate, turn-cap trips.
- Notifier interface; adapters mirror `broker/channels.py` (Slack, webhook, email).
- Config: `ObservabilityAlerts: [{metric, threshold, window, channel}]`.

**Acceptance:** dropping `routing_outcomes.confidence` to a configured threshold for N consecutive sessions fires a notification.

### Phase 6 — Online eval harness

- Scheduled broker job samples N recent sessions, runs an LLM-judge against a rubric, writes results into a new `eval_results` table joined to `session_id` + `turn_number`.
- Populates `routing_outcomes.quality_signal` (currently never written).
- `/feedback +1|-1|<text>` slash command and `feedback` event type joined to the last assistant turn.

**Acceptance:** scheduled run produces eval scores for recent sessions; thumbs-up/down from `/feedback` lands in the DB and is queryable.

### Phase 7 — Cost rollups, sampling, tool-output archival

- `user_id` column on `sessions`; aggregation into `cost_rollups` keyed by `(date, user, task_type, provider, model)`.
- Sampling policy: 100% retention for errors and high-cost sessions; configurable downsampling for low-cost successes.
- Separate `tool_outputs_raw` table (or blob store) for pre-truncation tool output; hash on `tool_calls` row.

**Acceptance:** cost-per-user / cost-per-task-type reports are available without scanning every event; low-cost successful sessions store metrics but not full prompts.

## Out of scope

- Replacing existing storage tiers — Phase 0 consolidates the *write path* (one authoritative event log; other sinks become projections per [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md)) and Phases 1–7 extend the current schema. No storage tier or table is replaced.
- A ground-up re-architecture or adopting OpenTelemetry as the *internal* event bus — rejected in [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md). The seams already exist; OTel stays an export projection (Phase 4), not the source of truth.
- Building a hosted observability backend — we're an OTel emitter; backend stays external (Langfuse / Phoenix / Datadog).
- Live tail UI — `/replay` is historical; live-tail is a possible follow-up.

## Related

- [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md) — single event log as source of truth; Phase 0 consolidation
- [observability-for-ai-agents.md](../best-practice/observability-for-ai-agents.md) — framework and rationale
- [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) — existing metrics design (Phase 1 builds on this)
- [DESIGN-memory-system.md](../design/DESIGN-memory-system.md) — existing persistence
- [PLAN-cost-metrics-logging.md](PLAN-cost-metrics-logging.md) — predecessor (completed)
- [PLAN-behavioural-eval-suite.md](PLAN-behavioural-eval-suite.md) — feeds Phase 6
- [session-memory-schema.md](../guides/session-memory-schema.md) — schema reference
