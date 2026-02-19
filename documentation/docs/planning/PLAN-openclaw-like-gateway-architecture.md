# Plan: OpenClaw-Like Gateway Architecture

## Goal

Move from single-process CLI orchestration to a local daemon architecture with clear separation between client, gateway, and execution runners.

## Target Topology (Local-First)

- `CLI/UI client`: interactive shell (and later optional UI) that sends requests and renders streamed events.
- `Gateway daemon`: long-lived local server handling sessions, routing, auth, rate limits, and persistence.
- `Runner workers`: isolated agent execution units that perform tool calls and stream state back to gateway.
- `Shared memory store`: SQLite initially, with interfaces that allow future Postgres migration if needed.

## Why This Architecture

- Allows resumable long-lived sessions independent of CLI process lifetime.
- Enables multi-client access to the same local agent state.
- Improves reliability via failure isolation (client crash does not kill gateway state).
- Creates a clean extension point for remote nodes later, without forcing cloud dependency now.

## Runtime Contracts

- Transport: WebSocket for bidirectional streaming, optional HTTP for management endpoints.
- Identity: gateway-issued `run_id`, `session_id`, `event_seq` for deterministic replay.
- Event model: gateway is source of truth for persisted event ordering.
- Tool execution policy: runner executes tools; gateway enforces policy/limits and checkpoint scopes.

## Architecture Diagram

```text
+-------------------+        WS/HTTP        +-----------------------------+
| CLI/UI Clients    | <-------------------> | Gateway Daemon              |
| - interactive CLI |                       | - session service           |
| - future web UI   |                       | - run service               |
+-------------------+                       | - scheduler service (cron)  |
                                            | - policy + auth + limits    |
                                            +--------------+--------------+
                                                           |
                                                           | enqueue run.start
                                                           v
                                            +--------------+--------------+
                                            | Runner Workers              |
                                            | - agent loop                |
                                            | - tool execution            |
                                            | - checkpoint hooks          |
                                            +--------------+--------------+
                                                           |
                                      persist events/state | restore checkpoints
                                                           v
                                            +--------------+--------------+
                                            | Shared Store (SQLite)       |
                                            | sessions/messages/tool_calls|
                                            | checkpoints/events           |
                                            | scheduled_jobs/job_runs      |
                                            +-----------------------------+
```

## Component Changes in This Repo

1. Add gateway package
- `src/micro_x_agent_loop/gateway/server.py` (daemon bootstrap)
- `src/micro_x_agent_loop/gateway/protocol.py` (request/response/event schema)
- `src/micro_x_agent_loop/gateway/session_service.py`
- `src/micro_x_agent_loop/gateway/run_service.py`

2. Extract runner package
- `src/micro_x_agent_loop/runner/worker.py` (agent execution loop)
- `src/micro_x_agent_loop/runner/execution_context.py` (session/checkpoint/tool context)
- Refactor current `Agent` to be runner-core, independent of CLI input loop.

3. Introduce client transport
- `src/micro_x_agent_loop/client/gateway_client.py` (WebSocket client)
- Update `src/micro_x_agent_loop/__main__.py` to run either:
- client mode (connect to local gateway), or
- single-process compatibility mode (current behavior).

4. Move memory ownership to gateway boundary
- Gateway owns `SessionManager`, `CheckpointManager`, pruning, and event persistence.
- Runner becomes mostly stateless per run except transient execution buffers.

5. Add operational controls
- Local auth token / loopback-only binding defaults.
- Graceful shutdown, heartbeat, and stale-run cancellation.
- Basic concurrency controls (`max_concurrent_runs`, per-session locks).

## Phased Rollout

### Phase A: Protocol + Compatibility Layer (Low Risk)

- Define gateway protocol models and event envelopes.
- Keep existing CLI flow; add in-process adapter that mimics gateway contracts.

Acceptance:

- No behavior regressions in current CLI mode.

### Phase B: Local Gateway Daemon (Medium Risk)

- Implement daemon + client transport + run/session services.
- Default binding to `127.0.0.1`; persist memory/events in same SQLite DB.

Acceptance:

- Restart CLI while preserving active sessions in gateway.

### Phase C: Runner Isolation (Medium/High Risk)

- Move tool execution into worker module/process boundary.
- Add run heartbeats, cancellation, timeout, and failure recovery semantics.

Acceptance:

- Runner failure does not corrupt gateway session state.

### Phase D: Multi-Client + Policy Controls (High Value)

- Support concurrent client attachments to same session (read-stream + controlled write lock).
- Add policy enforcement for tool allowlists, checkpoint requirements, and retention tiers.

Acceptance:

- Deterministic event ordering and lock behavior under concurrent clients.

### Phase E: Optional Remote Node Mode (Future)

- Allow gateway-to-runner over network transport for distributed execution.
- Keep local mode default and fully supported.

## API Sketch

Client -> Gateway:

- `session.create`
- `session.resume`
- `session.fork`
- `run.start` (user input + options)
- `run.cancel`
- `checkpoint.rewind`

Gateway -> Client events:

- `run.started`
- `message.delta` / `message.completed`
- `tool.started` / `tool.completed`
- `checkpoint.created`
- `rewind.completed`
- `run.completed` / `run.failed`

## Scheduled Jobs/Cron Plan

Goal:

- Support autonomous recurring runs with the same safety, memory, and observability guarantees as interactive runs.

Execution model:

- Gateway owns scheduling decisions and job lifecycle.
- Scheduler enqueues normal `run.start` requests when cron is due.
- Runner executes the job run using the same tool/checkpoint/memory pipeline.
- Results are persisted and streamed as normal run events.

Core scheduler behavior:

- Cron parsing with explicit timezone per job.
- Missed-run policy after downtime: `skip` or `run_once_on_recovery`.
- Overlap policy per job:
- `skip_if_running`
- `queue_one`
- `parallel` (only for explicitly safe workloads)
- Retry policy with capped exponential backoff.
- Manual trigger support (`run_now`) with same policy enforcement.

Suggested config knobs:

- `SchedulerEnabled` (bool, default `false`)
- `SchedulerPollIntervalSeconds` (int, default `5`)
- `SchedulerMaxConcurrentRuns` (int, default `2`)
- `SchedulerRecoveryPolicy` (`skip` or `run_once_on_recovery`)

Data model additions:

1. `scheduled_jobs`
- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `cron_expr TEXT NOT NULL`
- `timezone TEXT NOT NULL`
- `enabled INTEGER NOT NULL` (0/1)
- `target_session_id TEXT NULL`
- `prompt_template TEXT NOT NULL`
- `policy_json TEXT NOT NULL` (tool allowlist, timeout, overlap policy, retry)
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `last_run_at TEXT NULL`
- `next_run_at TEXT NOT NULL`

2. `job_runs`
- `id TEXT PRIMARY KEY`
- `job_id TEXT NOT NULL`
- `run_id TEXT NOT NULL`
- `scheduled_for TEXT NOT NULL`
- `started_at TEXT NULL`
- `completed_at TEXT NULL`
- `status TEXT NOT NULL` (`queued`, `running`, `completed`, `failed`, `cancelled`, `skipped`)
- `attempt INTEGER NOT NULL DEFAULT 1`
- `error_text TEXT NULL`

Indexes:

- `scheduled_jobs(enabled, next_run_at)`
- `job_runs(job_id, scheduled_for)`
- `job_runs(status, started_at)`

API additions:

Client -> Gateway:

- `job.create`
- `job.update`
- `job.pause`
- `job.resume`
- `job.delete`
- `job.list`
- `job.run_now`
- `job.get_runs`

Gateway -> Client events:

- `job.created`
- `job.updated`
- `job.triggered`
- `job.started`
- `job.completed`
- `job.failed`
- `job.skipped_overlap`

Safety and policy requirements:

- Per-job tool allowlist enforced at gateway before dispatch.
- Mandatory run timeout per job with cancellation on expiry.
- Optional requirement: checkpoint must be enabled for mutating tools.
- Default loopback binding and local auth for all scheduler management APIs.

Acceptance criteria:

- A cron job triggers at expected local time and creates a normal run with full event stream.
- Overlap policy is enforced deterministically under load.
- Gateway restart preserves schedule state and applies configured recovery policy.
- Failed jobs retry per policy and emit explicit failure events when exhausted.
- Interactive and scheduled runs share identical memory semantics and retention behavior.

## Feature Parity Requirements (Memory)

Architecture migration must not change user-visible memory semantics. The gateway rollout is complete only when parity is proven.

Required parity:

- Session behavior parity:
- `session.create`, `session.resume`, `session.fork`, and continue semantics behave identically to pre-gateway mode.
- Startup/session resolution precedence remains unchanged.

- Persistence parity:
- Same logical records are persisted (`sessions/messages/tool_calls/checkpoints/events`) with equivalent ordering guarantees.
- Resume reconstructs effective conversation context identically.

- Checkpoint/rewind parity:
- Same files are tracked under the same policy.
- `rewind` produces equivalent per-file outcomes (`restored`, `removed`, `skipped`, `failed`).

- Retention/safety parity:
- Existing retention limits, pruning behavior, and opt-in defaults remain unchanged unless explicitly versioned.

- Event parity:
- Same lifecycle event meanings and correlation IDs are preserved.
- Event ordering remains deterministic for a session/run.

Verification requirements:

- Golden transcript tests: run identical inputs in compatibility mode and gateway mode; compare persisted artifacts and assistant/tool sequence outputs.
- Rewind parity tests: execute identical mutating tool flows and compare checkpoint metadata + restore outcomes.
- Resume/fork parity tests: ensure same ancestry, sequence continuity, and context reconstruction.
- Failure-path parity tests: compare behavior on tool errors, cancellation, and process restart scenarios.

Change-control rule:

- Any intentional semantic change to memory behavior requires explicit plan update and versioned migration note before release.

## Risks and Mitigations

1. Protocol churn causes client/gateway incompatibility
- Mitigation: versioned protocol envelope and compatibility tests.

2. Event ordering bugs under concurrency
- Mitigation: gateway-side monotonic event sequence and single writer per session stream.

3. Tool execution isolation increases complexity
- Mitigation: start in-process worker abstraction first, then promote to separate process.

4. Operational overhead (daemon lifecycle) confuses users
- Mitigation: keep single-process mode and provide auto-start local gateway option.

## Success Criteria

- CLI can disconnect/reconnect without losing session continuity.
- Gateway restart behavior is predictable with persisted recovery state.
- Rewind/checkpoint works identically through gateway path.
- Event timelines remain deterministic and queryable.
- Single-process mode remains available until gateway mode is proven stable.
