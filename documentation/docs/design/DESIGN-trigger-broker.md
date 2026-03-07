# Design: Trigger Broker

## Overview

The trigger broker is a lightweight always-on daemon that dispatches autonomous agent runs on cron schedules. The key insight: the agent doesn't need to be always-on — only the trigger router does. The agent cold-starts via `--run`, executes a prompt, persists results, and exits. The broker handles scheduling, concurrency, and run tracking.

## Architecture

```
CLI (--broker / --job)
  |
  v
cli.py ──────────────────────────────────────────────┐
  |                                                   |
  |  [--broker start]                                 |  [--job add/list/run-now/runs]
  v                                                   v
BrokerService (service.py)                    BrokerStore (store.py)
  |  PID lock, signal handling                   SQLite CRUD
  |  graceful shutdown                           broker_jobs + broker_runs
  v
Scheduler (scheduler.py)
  |  poll loop (every N seconds)
  |  cron evaluation via croniter
  |  overlap policy enforcement
  |  concurrency limiting
  v
runner.run_agent()  (runner.py)
  |  asyncio.create_subprocess_exec
  |  [python -m micro_x_agent_loop --run "prompt"]
  v
Agent (one-shot, autonomous mode)
  |  no ask_user, no voice, no mode analysis prompts
  |  autonomy directive in system prompt
  v
BrokerStore: complete_run / fail_run
```

## Components

### BrokerService (`service.py`)

Daemon lifecycle manager. Responsible for:

- **PID-based locking** — writes PID file on start, checks for stale PIDs, prevents multiple broker instances
- **Signal handling** — registers SIGINT/SIGTERM handlers for graceful shutdown
- **Scheduler ownership** — creates and starts the Scheduler, waits for it to stop
- **Cleanup** — closes BrokerStore and removes PID file on exit

External callers use static methods `read_pid()` and `stop_broker()` for status queries and remote stop.

### Scheduler (`scheduler.py`)

Cron polling loop. Responsible for:

- **Schedule initialisation** — on startup, computes `next_run_at` for all enabled jobs that don't have one
- **Poll-and-dispatch** — every `poll_interval` seconds, queries jobs where `next_run_at <= now`
- **Overlap policy** — `skip_if_running` checks `has_running_run()` before dispatch; skipped runs get a `skipped` record
- **Concurrency limiting** — respects `max_concurrent_runs` across all jobs
- **Run lifecycle** — creates run record before dispatch, spawns async task, updates status on completion/failure
- **Schedule advancement** — after dispatch, computes next run time via croniter with timezone support

### BrokerStore (`store.py`)

SQLite persistence layer. Two tables:

**`broker_jobs`** — job definitions (cron expression, prompt template, timezone, overlap policy, session/config overrides)

**`broker_runs`** — execution history (status, timestamps, stdout summary, error text)

Key behaviours:
- WAL mode for safe concurrent reads during writes
- Indexes on `(enabled, next_run_at)` for efficient poll queries
- Indexes on `(job_id, started_at)` and `(status, started_at)` for run history queries
- All writes commit immediately (no batching)

### Runner (`runner.py`)

Subprocess dispatcher. The `run_agent()` async function:

1. Builds command: `[python, -m, micro_x_agent_loop, --run, <prompt>, ...]`
2. Appends optional `--config` and `--session` flags from job definition
3. Spawns via `asyncio.create_subprocess_exec` with stdout/stderr capture
4. Applies timeout if configured — kills process on expiry
5. Returns `RunResult` dataclass with `exit_code`, `stdout`, `stderr`, and convenience properties (`ok`, `summary`)

The subprocess inherits the broker's environment (including `.env` variables). The agent runs in full autonomous mode — `--run` flag triggers autonomous configuration in `__main__.py`.

### CLI (`cli.py`)

Two entry points routed from `__main__.py`:

**`handle_broker_command(args, config)`** — `--broker start|stop|status`
- `start`: creates BrokerService, runs `await service.start()` (blocks until shutdown)
- `stop`: sends signal to running broker via PID
- `status`: reads PID, queries store for job/run counts

**`handle_job_command(args, config)`** — `--job add|list|remove|enable|disable|run-now|runs`
- `add`: validates cron expression, creates job with name/cron/prompt and optional flags
- `run-now`: manual trigger — creates run record, awaits `run_agent()`, prints output inline
- `runs`: lists run history with status icons and error/summary details

## Autonomous Mode

When the agent is launched via `--run`, it operates without human interaction:

1. `ask_user` pseudo-tool is removed from the tool set
2. Mode analysis user prompts are suppressed
3. Voice ingress is disabled
4. System prompt includes an autonomy directive: proceed with best judgement or report inability to continue

Job prompts must be self-contained. If a job regularly needs clarification, it's a poorly designed job.

## Cron Evaluation

Cron expressions are evaluated using `croniter` with timezone support via `ZoneInfo`:

- Each job stores a `timezone` (IANA, e.g. `Australia/Sydney`) and a `cron_expr` (standard 5-field)
- `compute_next_run()` helper converts cron to next UTC datetime for comparison
- The poll loop compares `next_run_at` against `datetime.now(UTC)` — timezone math is handled at schedule computation time, not poll time

## Concurrency and Overlap

Two controls prevent resource exhaustion:

1. **Per-job overlap policy** (`overlap_policy` column):
   - `skip_if_running` — if a previous run of the same job is still active, skip and record a `skipped` run
   - `queue_one` — reserved for future use

2. **Global concurrency limit** (`max_concurrent_runs`):
   - Counts active async tasks across all jobs
   - New dispatches wait until a slot opens

## Data Flow: Scheduled Run

```
1. Scheduler._poll_and_dispatch()
     queries: SELECT * FROM broker_jobs WHERE enabled=1 AND next_run_at <= now
2. For each due job:
     check overlap policy (skip_if_running → has_running_run?)
     check global concurrency limit
3. Scheduler._dispatch_job()
     BrokerStore.create_run(job_id, prompt, status='running')
     spawn async task → _execute_run()
     advance schedule → compute_next_run(), update next_run_at
4. Scheduler._execute_run()
     runner.run_agent(prompt, config, session_id, timeout)
     if ok: BrokerStore.complete_run(run_id, summary)
     else:  BrokerStore.fail_run(run_id, error_text)
```

## Error Handling

| Error | Handling |
|-------|----------|
| Broker already running | PID check on start; prints message and exits |
| Stale PID file | Detected via `kill(pid, 0)`; cleaned up automatically |
| Subprocess crash | Exit code captured; run status set to `failed` with stderr |
| Subprocess timeout | Process killed; run status set to `failed` with timeout message |
| Invalid cron expression | Validated at `--job add` time; rejected with error message |
| Store connection failure | Exception propagates; broker exits with error |
| Signal during in-flight runs | Scheduler waits for running tasks before exit |

## Configuration

Broker settings in `config.json`:

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `BrokerEnabled` | bool | `true` | Enable broker functionality |
| `BrokerHost` | string | `127.0.0.1` | Bind address (Phase 2: webhook server) |
| `BrokerPort` | int | `8321` | Port (Phase 2: webhook server) |
| `BrokerPollIntervalSeconds` | int | `5` | Seconds between schedule checks |
| `BrokerMaxConcurrentRuns` | int | `2` | Max simultaneous agent runs |
| `BrokerRecoveryPolicy` | string | `skip` | Missed-run policy after downtime (Phase 3) |
| `BrokerDatabase` | string | `.micro_x/broker.db` | SQLite database path |

## Related Documents

- [PLAN-trigger-broker.md](../planning/PLAN-trigger-broker.md) — feature plan with phased rollout
- [ADR-018](../architecture/decisions/ADR-018-trigger-broker-subprocess-dispatch.md) — decision record for subprocess dispatch model
- [Trigger Broker Operations](../operations/trigger-broker.md) — setup and usage guide
