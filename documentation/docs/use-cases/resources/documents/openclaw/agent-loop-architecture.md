# OpenClaw Agent Loop Architecture (Deep Dive)

## Scope
This document explains how the OpenClaw agent loop works end-to-end, from request entry to model execution, tool calls, streaming events, delivery, persistence, aborts, and retries.

Primary focus areas:
- Request ingress paths (CLI local, CLI via Gateway, Gateway RPC)
- Session resolution and run context setup
- Embedded runner execution loop (including tool and compaction behavior)
- Event pipeline (agent events -> gateway chat stream -> clients)
- Reliability controls (dedupe, lanes, timeouts, abort, retries/fallbacks)
- State updates (session store, transcript, run snapshots)

---

## 1) Mental Model
At runtime, OpenClaw’s agent loop is a layered pipeline:

1. A caller submits a prompt (`openclaw agent ...`, `agent` RPC, or `chat.send`).
2. Request/session context is resolved (agent, session key/id, channel/account/thread).
3. A run is created (`runId`), and lifecycle/events are tracked.
4. The embedded agent (or CLI provider path) executes the prompt.
5. Tool events, assistant deltas, and lifecycle events stream out.
6. Final payloads are assembled and optionally delivered to messaging channels.
7. Session/transcript metadata is persisted.
8. Run state is cleaned up.

OpenClaw treats the Gateway as control plane and the embedded runner as execution engine.

---

## 2) Entry Points and Control Paths

### 2.1 CLI command path
Main CLI command implementation:
- `src/commands/agent.ts`
- `src/commands/agent-via-gateway.ts`

Behavior:
- `agentCliCommand` prefers gateway mode unless `--local` is set.
- Gateway mode calls RPC `agent` and can fall back to local embedded execution if gateway call fails.
- Local mode runs `agentCommand` directly.

Key detail:
- In gateway mode, `runId` is effectively the request idempotency key (`idempotencyKey`), so retries can dedupe and refer to the same run.

### 2.2 Gateway RPC agent path
Gateway handler:
- `src/gateway/server-methods/agent.ts`

Behavior:
- Validates params and normalizes attachments.
- Resolves/validates agent id + session key/id.
- Handles `/new` and `/reset` inline behavior (via session reset handler).
- Creates accepted ACK response immediately.
- Spawns async `agentCommand(...)` execution.
- Emits a second response (same request id) when final result/error is ready.

Why this matters:
- RPC clients can receive fast acknowledgment and optionally wait for final completion.

### 2.3 Gateway chat path (adjacent)
Related surface:
- `src/gateway/server-methods/chat.ts`

`chat.send`/`chat.abort` use the same event substrate and abort infrastructure as agent runs, so UI behavior is consistent across chat and direct agent calls.

---

## 3) Session and Run Context Resolution

Core session resolution logic:
- `src/commands/agent/session.ts`
- `src/commands/agent/run-context.ts`
- `src/gateway/server-session-key.ts`

What is resolved:
- `sessionId` and `sessionKey`
- agent identity from session key (or explicit override)
- channel/account/thread/group context for tools and delivery
- stored per-session overrides (thinking, verbose, model/provider overrides)

Important behaviors:
- Session IDs can be looked up across per-agent stores when needed.
- Session freshness policy can force a new session id even with existing key.
- Session run context is normalized so tooling and delivery share consistent channel/account/thread values.

---

## 4) Event Substrate: Agent Events as the Backbone

Shared event bus:
- `src/infra/agent-events.ts`

Properties:
- Global run event emitter with monotonic per-run sequence numbers.
- Streams include: `lifecycle`, `assistant`, `tool`, `thinking`, `error`, etc.
- Optional run context cache (`sessionKey`, `verboseLevel`, heartbeat flag).

Why it is central:
- Embedded runner emits events here.
- Gateway subscribes and fans out to websocket clients + node subscribers.
- Agent wait/status tooling consumes lifecycle snapshots derived from this stream.

---

## 5) Gateway Runtime Wiring Around the Loop

Gateway runtime state:
- `src/gateway/server-runtime-state.ts`
- `src/gateway/server.impl.ts`
- `src/gateway/server-chat.ts`

Constructed runtime structures include:
- `agentRunSeq`: per-run stream sequence tracking at gateway edge
- `dedupe`: idempotency cache for request replay protection
- `chatRunState`: buffers/delta throttling/abort markers
- `chatAbortControllers`: active run abort handles
- tool event recipient registry for capability-gated delivery

Wiring:
- `onAgentEvent(createAgentEventHandler(...))` in `server.impl.ts` attaches agent-event fanout logic.

---

## 6) Agent Command Orchestration (Pre-run)

Main orchestrator:
- `src/commands/agent.ts`

High-level stages:
1. Validate message and routing inputs.
2. Resolve workspace + agent directory.
3. Resolve session + load/persist per-session overrides.
4. Register run context (`registerAgentRunContext`).
5. Build skill snapshot when needed.
6. Resolve model/provider + fallback policy.
7. Execute attempt(s) via `runWithModelFallback(...)`.
8. Ensure lifecycle terminal event (`end` or `error`) is emitted.
9. Persist post-run session metadata.
10. Deliver or print payloads.
11. Always clear run context in `finally`.

---

## 7) Execution Engine: Embedded Runner

Top-level runner entry:
- `src/agents/pi-embedded-runner/run.ts`

Attempt worker:
- `src/agents/pi-embedded-runner/run/attempt.ts`

### 7.1 Queueing and lanes
Queue infrastructure:
- `src/process/command-queue.ts`
- lane resolution in `src/agents/pi-embedded-runner/lanes.ts`

Execution model:
- Runs are serialized by session lane (`session:<key>`), plus a global lane.
- This preserves per-session ordering while allowing controlled concurrency across lanes.
- Queue supports wait diagnostics and lane clearing semantics.

### 7.2 Attempt setup
Per-attempt preparation includes:
- workspace and sandbox resolution
- skill env and skill prompt setup
- session manager/init and transcript integrity repairs
- toolset construction (`createOpenClawCodingTools` + optional client tools)
- provider/model stream setup (including provider-specific handling)

### 7.3 Live subscription and streaming
Subscription setup:
- `subscribeEmbeddedPiSession(...)` in `src/agents/pi-embedded-subscribe.ts`

This layer:
- consumes model/agent SDK events
- emits normalized `agent-events` (`assistant`, `tool`, `thinking`, `lifecycle`)
- tracks assistant text chunks, reasoning streams, tool summaries/results, messaging-tool dedupe
- coordinates compaction retry synchronization

### 7.4 Active-run registration and steering/abort handles
Run handle registry:
- `src/agents/pi-embedded-runner/runs.ts`

Provides:
- `setActiveEmbeddedRun`, `clearActiveEmbeddedRun`
- external message steering (`queueEmbeddedPiMessage`)
- abort (`abortEmbeddedPiRun`)
- streaming/active checks and run-end waiting

### 7.5 Timeout and abort behavior
In attempt loop:
- timeout timer triggers `abortRun(true)`
- external abort signals are honored
- compaction-timeout conditions are tracked distinctly
- cleanup always unsubscribes, clears active run, removes listeners, and releases locks

### 7.6 Post-attempt result materialization
Result object includes:
- `assistantTexts`, `toolMetas`, last assistant message
- tool error summary and messaging-tool sent metadata
- usage and compaction counts
- optional pending hosted tool calls (`stopReason: tool_calls` path)

---

## 8) Tool and Message Event Handling Internals

Handlers:
- `src/agents/pi-embedded-subscribe.handlers.messages.ts`
- `src/agents/pi-embedded-subscribe.handlers.tools.ts`
- `src/agents/pi-embedded-subscribe.handlers.lifecycle.ts`

### 8.1 Message stream handling
- Aggregates `text_delta` / `text_start` / `text_end` safely (handles repeated/lated end behavior).
- Produces monotonic cleaned assistant text and deltas.
- Emits `assistant` events with `text` and `delta`.
- Emits final assistant update on `message_end` if no incremental update was emitted.

### 8.2 Tool lifecycle handling
- Emits `tool` events for phases: `start`, `update`, `result`.
- Tracks per-tool metadata, mutation fingerprints, and last tool error semantics.
- Supports plugin `after_tool_call` hooks.
- Supports optional tool output/result emission to user surfaces depending on verbosity.

### 8.3 Lifecycle handling
- Emits `lifecycle:start` on agent start.
- Emits `lifecycle:end` or `lifecycle:error` on completion.
- Unblocks compaction waiters and flushes reply buffers at end.

---

## 9) Compaction and Context Overflow Recovery

Core logic in:
- `src/agents/pi-embedded-runner/run.ts`

Recovery strategy (simplified):
1. Detect likely context overflow from prompt/assistant error signals.
2. If in-attempt compaction already occurred, retry prompt first.
3. Else run explicit overflow compaction (`compactEmbeddedPiSessionDirect`).
4. If still failing, attempt oversized tool-result truncation.
5. If unrecoverable, return explicit user-facing context-overflow error payload.

Additional safeguards:
- compaction timeout-aware snapshot selection
- cache-ttl timestamp handling after prompt/compaction retry
- bounded overflow-compaction attempts

---

## 10) Model/Auth/Profile Failover Loop

Implemented in `run.ts` around attempt loop.

Behavior:
- Resolve profile order and current usable auth profile.
- Mark profile failures on timeout/rate-limit/auth/failover-classified errors.
- Rotate profiles where possible.
- Optionally downgrade thinking level when model/provider rejects selected reasoning mode.
- Throw `FailoverError` with classified reason/status when fallback to other models/providers should trigger.

This interacts with `runWithModelFallback(...)` in `agent.ts`.

---

## 11) Gateway Event Fanout and Chat State

Fanout handler:
- `src/gateway/server-chat.ts` (`createAgentEventHandler`)

Responsibilities:
- Validate stream sequence continuity (`agentRunSeq`) and log gaps.
- Broadcast `agent` stream to ws clients.
- Route tool events to capability-approved recipients.
- Build and throttle chat deltas/finals from assistant events.
- Handle aborted run cleanup and finalization.
- Send per-session updates to node subscribers.

State used:
- run registry queues (`chatRunState.registry`)
- delta buffers / throttling maps
- aborted runs map

---

## 12) Abort Semantics

Shared abort infrastructure:
- `src/gateway/chat-abort.ts`
- used by `chat.send`, `chat.abort`, and maintenance cleanup paths

Key points:
- abort can target a single run or all runs for a session key
- partial assistant text can be persisted into transcript on abort paths (chat flow)
- sequence and run registry state are cleaned to avoid stale in-flight artifacts

---

## 13) Response/Delivery Stage

Delivery handling:
- `src/commands/agent/delivery.ts`

Pipeline:
1. Build normalized outbound payloads.
2. If `--deliver`, resolve channel/target/account/thread using delivery planner.
3. Validate explicit vs implicit target policy.
4. Deliver via channel sender deps, optionally best-effort.
5. For non-deliver mode, print/log payloads locally.

Nested/subagent lanes use prefixed logs to keep parent run output readable.

---

## 14) Session Store and Metadata Updates

Post-run update path:
- `src/commands/agent/session-store.ts`

Persists run-derived metadata such as:
- model/provider used (after fallback resolution)
- token/cost usage summaries
- context token sizing fields
- compaction counters
- aborted-last-run flags
- CLI-provider session IDs when relevant

Session map updates are written back through `updateSessionStore(...)`.

---

## 15) Dedupe and Idempotency

Dedupe cache is maintained in gateway runtime state and used heavily by `agent` RPC.

Pattern in `server-methods/agent.ts`:
- cache accepted ACK immediately (`status: accepted`) keyed by `agent:<idempotencyKey>`
- retries return cached response instead of launching duplicate runs
- once async run finishes, cache updated with final success/error payload

Net effect:
- robust client retries without duplicated model executions.

---

## 16) `agent.wait` and Run Snapshotting

Run snapshot subsystem:
- `src/gateway/server-methods/agent-job.ts`
- endpoint: `agent.wait` in `server-methods/agent.ts`

Mechanism:
- listens to lifecycle events and caches short-lived run status snapshots
- supports polling by `runId` with timeout
- statuses: `ok`, `error`, `timeout`

This gives clients a stable completion-check API independent of streaming connection behavior.

---

## 17) Architecture Invariants

The loop relies on a few critical invariants:

1. Per-run sequence monotonicity (`emitAgentEvent` + gateway checks).
2. Session-lane serialization for deterministic per-session behavior.
3. `finally` cleanup always runs (clear run context, unsubscribe, release locks, clear active run).
4. Idempotency key uniqueness per logical request to avoid duplicate execution.
5. Lifecycle terminal event (`end`/`error`) should always be emitted exactly once per run path.

---

## 18) Practical End-to-End Sequence (Gateway `agent` RPC)

1. Client sends `agent` RPC with `idempotencyKey`.
2. Gateway validates params, resolves session, stores/updates session entry.
3. Gateway responds immediately with `accepted`.
4. Gateway invokes `agentCommand(...)` async.
5. `agentCommand` resolves model/profile/skills/session context and starts embedded run.
6. Embedded subscription emits `lifecycle:start`, then `assistant`/`tool`/`thinking` streams.
7. Gateway event handler fans out to websocket and session subscribers; chat delta/final packets are generated.
8. Embedded runner completes; payloads are built.
9. `agentCommand` persists session metadata and performs optional delivery.
10. Gateway sends final response for the original request id.
11. Cleanup removes run context and active run handles.

---

## 19) Key Files Index

Core orchestration:
- `src/commands/agent.ts`
- `src/commands/agent-via-gateway.ts`
- `src/gateway/server-methods/agent.ts`

Runner internals:
- `src/agents/pi-embedded-runner/run.ts`
- `src/agents/pi-embedded-runner/run/attempt.ts`
- `src/agents/pi-embedded-runner/runs.ts`
- `src/agents/pi-embedded-subscribe.ts`
- `src/agents/pi-embedded-subscribe.handlers.messages.ts`
- `src/agents/pi-embedded-subscribe.handlers.tools.ts`
- `src/agents/pi-embedded-subscribe.handlers.lifecycle.ts`

Event and gateway fanout:
- `src/infra/agent-events.ts`
- `src/gateway/server-chat.ts`
- `src/gateway/server-runtime-state.ts`
- `src/gateway/server.impl.ts`

Abort/status/session updates:
- `src/gateway/chat-abort.ts`
- `src/gateway/server-methods/agent-job.ts`
- `src/commands/agent/session.ts`
- `src/commands/agent/session-store.ts`
- `src/commands/agent/delivery.ts`

---

## 20) Summary
OpenClaw’s agent loop is not a single function; it is a coordinated runtime architecture:
- Gateway controls ingress, dedupe, routing, fanout, and client-facing run semantics.
- The embedded runner executes model/tool loops with strong recovery and cleanup semantics.
- Event streaming is first-class and drives UI/state updates in real time.
- Session and delivery systems are tightly integrated so context, routing, and outbound behavior remain consistent across channels and clients.

This structure gives OpenClaw strong operational characteristics for real-time, multi-channel, long-running assistant behavior.
