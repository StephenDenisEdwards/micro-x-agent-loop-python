# Plan: Trigger Broker (Always-On Run Dispatcher)

## Status

**Phase 2a+ In Progress** (2026-03-07) — Replaces [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) at priority #11.

- Phase 1 (cron + autonomous mode): **Complete** (2026-03-06)
- Phase 1 hardening (architecture review fixes): **Complete** (2026-03-07)
- Phase 2a (webhook ingress + response routing + HTTP adapter): **Complete** (2026-03-07)
- Phase 2a+ (WhatsApp + Telegram adapters): **In Progress**
- Phase 2b (async human-in-the-loop): **Complete** (2026-03-07)
- Phase 3 (operational hardening): **Complete** (2026-03-07)

## Goal

Add a lightweight always-on service that can receive triggers (cron schedules, webhooks, message polling) and dispatch agent runs, routing results back to the originating channel.

**Future direction:** The broker's HTTP API and channel adapter pattern are designed to evolve into a multi-client API layer, where any frontend (web app, CLI, WhatsApp, Messenger) can drive the agent as a client.

## Background and Decision Record

The original plan ([PLAN-openclaw-like-gateway-architecture.md](PLAN-openclaw-like-gateway-architecture.md)) proposed a full OpenClaw-style gateway daemon with WebSocket transport, runner worker isolation, multi-client session sharing, and policy enforcement. After analysis, this was determined to be over-engineered for the actual use cases.

### Use cases driving this work

1. **Scheduled/cron tasks** — run agent jobs on a timer (e.g., daily content publishing, periodic data checks)
2. **Remote control via messaging** — trigger agent runs from WhatsApp, Telegram, email, or other channels
3. **Multi-client frontends (future)** — any frontend app (web, CLI, messaging) should be able to drive the agent

### Why not a full gateway?

A full gateway solves real problems — but they're not our problems right now:

| Gateway capability | Needed? | Reasoning |
|---|---|---|
| Live session sharing across clients | No | Single-user tool |
| Warm MCP connections between runs | No | Tool search means only needed servers start; cold start cost is proportional to tools used, not total configured |
| Mid-run interactive control | No | Cron and messaging are async/fire-and-forget |
| Real-time multi-run observability | No | Can add a simple status endpoint without a gateway |
| Sub-second follow-up latency | No | WhatsApp/email are inherently async — nobody expects instant agent replies |
| Multi-tenant cloud hosting | No | Local-first, single-user |

### Key insight

**The agent doesn't need to be always-on — the trigger/response router does.** The agent already supports session persistence, resume, and checkpoint/rewind. It can cold-start, resume a session, do work, persist results, and exit. The always-on piece is just the thin layer that receives triggers and dispatches runs.

### MCP cold start mitigation

Tool search (on-demand MCP server discovery) means only the MCP servers actually needed for a given run are started. A cron job that posts to Dev.to pays the startup cost of one MCP server, not all configured servers. This removes the main argument for keeping MCP connections warm in a persistent daemon.

## Architecture

```text
+-------------------+
| Trigger Sources   |
| - Cron scheduler  |
| - Webhook server  |     +------------------------+
| - Message polling  | --> | Trigger Broker         |
| - HTTP endpoint   |     | (always-on, lightweight)|
| - File watcher    |     +----------+-------------+
+-------------------+                |
                                     | dispatch run
                                     v
                          +----------+-------------+
                          | Agent Run              |
                          | (one-shot process/task)|
                          | - resume session       |
                          | - execute prompt       |
                          | - persist results      |
                          | - exit                 |
                          +----------+-------------+
                                     |
                                     | results
                                     v
                          +----------+-------------+
                          | Response Egress        |
                          | - WhatsApp reply       |
                          | - Telegram reply       |
                          | - Email response       |
                          | - Log/persist          |
                          | - Webhook callback     |
                          +------------------------+
```

## Components

### 1. Channel Adapters (Phase 2a)

Every external channel implements the same `ChannelAdapter` protocol for both ingress and egress. Adding a new channel = adding a new adapter.

**Trigger filtering** is a config concern, not a channel concern. All messaging channels face the same problem: which messages are agent triggers vs. noise. A unified `TriggerFilter` handles this with `chat_ids`, `sender_ids`, and `prefix` fields (AND logic when multiple set).

Implemented adapters:
- **HttpAdapter** — generic webhook trigger with bearer token auth
- **LogAdapter** — fallback egress that logs results (always present)

Planned adapters:
- **WhatsAppAdapter** — polling via existing MCP server or Cloud API webhooks
- **TelegramAdapter** — Bot API long-polling or webhooks

### 2. Run Dispatcher (Phase 2a)

Shared dispatch logic used by both the cron scheduler and webhook server:
- Creates run records and spawns agent subprocesses
- Routes responses on completion via the ResponseRouter
- Tracks active tasks and enforces concurrency limits

### 3. Response Router (Phase 2a)

Routes completed run results to the appropriate channel adapter. Falls back to log channel if the configured channel fails. Tracks delivery status on each run record.

### 4. Webhook Server (Phase 2a)

FastAPI server running inside the broker as a parallel asyncio task:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Health check (job count, active runs, channels) |
| `POST /api/trigger/{channel}` | Webhook ingress (dispatches a run via channel adapter) |
| `GET /api/runs/{run_id}` | Query run status and result |
| `GET /api/jobs` | List configured jobs |

The `/api/` prefix reserves URL space for the future multi-client API (`/api/run`, `/api/run/{id}/stream`).

### 5. Cron Scheduler

In-process polling loop using croniter with timezone support. Delegates dispatch to the shared RunDispatcher.

### 6. Job/Schedule Store

SQLite persistence (`broker_jobs` + `broker_runs` tables) in `.micro_x/broker.db`.

## Data Model

### `broker_jobs`

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| name | TEXT NOT NULL | Human-readable job name |
| trigger_type | TEXT NOT NULL | `cron`, `webhook`, `poll` |
| cron_expr | TEXT NULL | Cron expression (for cron triggers) |
| timezone | TEXT NULL | IANA timezone (for cron triggers) |
| enabled | INTEGER NOT NULL | 0/1 |
| prompt_template | TEXT NOT NULL | Prompt to send to agent |
| session_id | TEXT NULL | Resume this session, or NULL for new |
| config_profile | TEXT NULL | Config file override |
| response_channel | TEXT NOT NULL | `whatsapp`, `telegram`, `http`, `email`, `log`, `none` |
| response_target | TEXT NULL | Channel-specific target (phone number, chat ID, URL) |
| overlap_policy | TEXT NOT NULL | `skip_if_running`, `queue_one` |
| timeout_seconds | INTEGER NULL | Max run duration (default: 1 hour) |
| created_at | TEXT NOT NULL | ISO 8601 |
| updated_at | TEXT NOT NULL | ISO 8601 |
| last_run_at | TEXT NULL | ISO 8601 |
| next_run_at | TEXT NULL | ISO 8601 |

### `broker_runs`

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| job_id | TEXT NULL | FK to broker_jobs (NULL for ad-hoc triggers), CASCADE on delete |
| trigger_source | TEXT NOT NULL | `cron`, `whatsapp`, `telegram`, `http`, `manual`, etc. |
| prompt | TEXT NOT NULL | Actual prompt sent |
| session_id | TEXT NULL | Session used |
| status | TEXT NOT NULL | `queued`, `running`, `completed`, `failed`, `cancelled`, `skipped` |
| started_at | TEXT NULL | ISO 8601 |
| completed_at | TEXT NULL | ISO 8601 |
| result_summary | TEXT NULL | Brief output or error |
| error_text | TEXT NULL | Error details if failed |
| response_channel | TEXT NULL | Channel used for response routing |
| response_target | TEXT NULL | Target for response routing |
| response_sent | INTEGER NOT NULL | 0/1 — whether response was sent |
| response_error | TEXT NULL | Error if response failed |

## Trigger Filtering

Every messaging channel adapter uses the same `TriggerFilter` to decide which messages are agent triggers:

| Filter field | Type | Meaning |
|---|---|---|
| `chat_ids` | list or null | Only messages from these chats/groups |
| `sender_ids` | list or null | Only messages from these senders |
| `prefix` | string or null | Only messages starting with this prefix (stripped from prompt) |

All fields optional. When multiple are set, all must match (AND). Empty filter = accept all messages.

**Examples:**
- WhatsApp dedicated group: `{"chat_ids": ["120363xxx@g.us"]}`
- WhatsApp keyword: `{"prefix": "/agent"}`
- Telegram bot (all messages): `{}`
- Telegram restricted: `{"sender_ids": ["123456789"]}`

## Human Interaction in Autonomous Runs

The interactive agent uses `ask_user` for human-in-the-loop questioning and mode analysis prompts. Broker-dispatched runs have no human at the keyboard. This requires a strategy for handling situations where the agent would normally ask for input.

### Phase 1: Fully autonomous (no human input) — Complete

Broker runs operate in autonomous mode:
- `ask_user` tool is removed from the tool set
- Mode analysis user prompts are disabled
- Voice ingress is disabled (runtime not even initialized)
- System prompt includes an autonomy directive: the agent cannot ask questions and must either proceed with its best judgement or report that it cannot continue

Job prompts must be written to be self-contained — if a cron job regularly needs human input, it's a poorly designed job.

**Limitation:** Some tasks genuinely benefit from clarification. A fully autonomous agent may make wrong assumptions or fail where a single question would have unblocked it.

### Phase 2b: Asynchronous human-in-the-loop (planned)

When webhook ingress and response routing exist, the agent could route questions to the originating channel and wait for a reply:

- Agent calls `ask_user` → broker intercepts and sends the question to the trigger channel (WhatsApp, Telegram, email)
- Broker suspends the run and waits for a response with a configurable timeout
- When the human replies, the broker resumes the run with the answer
- On timeout: either fail the run or provide a default "no response" answer so the agent can adapt

This turns the agent into an async conversational partner — it asks, waits, and continues when it gets an answer. The trigger channel doubles as the response channel.

**Design considerations:**
- Run state must be serialisable so it can survive broker restart during the wait
- Timeout policy per job: how long to wait before giving up
- The agent's context window stays warm during the wait (in-process) or must be reconstructable (subprocess)
- Multiple questions per run: each question is a separate round-trip through the channel

### Phase 3: Multi-channel escalation (future)

For critical jobs, questions could escalate across channels:
- Try WhatsApp first, if no reply in 5 minutes escalate to email
- If no reply on any channel within the job timeout, fail with explanation

This is speculative and depends on Phase 2b proving the single-channel pattern works.

## Phased Rollout

### Phase 1: Core Broker + Cron — Complete (2026-03-06)

- `--run "prompt"` one-shot CLI flag for non-interactive agent execution
- Autonomous mode: strips `ask_user`, disables interactive features, adds autonomy system prompt directive
- Broker service with cron scheduler
- Agent run dispatch (subprocess via `--run`)
- Job store (SQLite)
- Log-based response egress
- CLI management: `--broker start`, `--broker stop`, `--broker status`
- Job management: `--job add`, `--job list`, `--job remove`, `--job run-now`

### Phase 1 Hardening — Complete (2026-03-07)

Architecture review identified and fixed:
- Atomic PID file creation (O_CREAT|O_EXCL) to prevent race conditions
- Scheduler exponential backoff on errors with max consecutive error limit
- Atomic overlap policy check via BEGIN IMMEDIATE transaction in SQLite
- Subprocess output capped at 10MB to prevent OOM
- Default subprocess timeout of 1 hour (was infinite)
- Foreign key constraints on broker_runs with ON DELETE CASCADE
- Voice runtime not initialized in autonomous mode (resource efficiency)

### Phase 2a: Webhook Ingress + Response Routing — Complete (2026-03-07)

- `ChannelAdapter` protocol with unified `TriggerFilter` for message filtering
- `HttpAdapter` for generic HTTP triggers with bearer token auth
- `LogAdapter` fallback for response egress
- FastAPI `WebhookServer` with `/api/trigger/{channel}`, `/api/health`, `/api/jobs`, `/api/runs/{id}`
- `RunDispatcher` extracted from scheduler — shared by cron and webhooks
- `ResponseRouter` with fallback to log channel on failure
- Response tracking columns on `broker_runs` (channel, target, sent, error)
- Schema migration for existing databases
- CLI: `--job add` accepts `--response-channel` and `--response-target`

### Phase 2a+: Messaging Channel Adapters — In Progress

- `PollingIngress` loop for channels using polling mode
- `WhatsAppAdapter` (polling via existing MCP server with trigger filter, egress via MCP)
- `TelegramAdapter` (Bot API long-polling with trigger filter, egress via Bot API)

### Phase 2b: Async Human-in-the-Loop — Complete (2026-03-07)

- `BrokerAskUserHandler` — posts questions to broker HTTP API, polls for answers
- Broker question endpoints: `POST /api/runs/{run_id}/questions`, `GET .../questions/{qid}`, `POST .../questions/{qid}/answer`
- `send_question` on `ChannelAdapter` protocol — routes questions to originating channel
- `broker_questions` table with auto-timeout on expired pending questions
- Per-job `hitl_enabled` and `hitl_timeout_seconds` configuration
- Agent detects `MICRO_X_BROKER_URL`/`MICRO_X_RUN_ID` env vars and switches to HITL mode
- HITL system prompt directive (use `ask_user` sparingly, expect async delays)
- CLI: `--job add` accepts `--hitl` and `--hitl-timeout` flags

### Phase 3: Operational Hardening — Complete (2026-03-07)

- Retry policy: per-job `max_retries` + `retry_delay_seconds` with exponential backoff
- Failed runs auto-schedule queued retry with `scheduled_at` and incremented `attempt_number`
- Scheduler picks up due retries alongside cron jobs
- Missed-run recovery on broker start: `skip` (advance schedule) or `run_once` (dispatch on next poll)
- Bearer token auth middleware on management endpoints (`BrokerApiSecret` config)
- CLI: `--job add` accepts `--max-retries` and `--retry-delay` flags

Note: some Phase 3 items were addressed early:
- Run timeout and cancellation — done in Phase 1 hardening (default 1-hour timeout)
- Health check endpoint — done in Phase 2a (`GET /api/health`)

## Configuration

```json
{
  "BrokerEnabled": true,
  "BrokerWebhookEnabled": true,
  "BrokerHost": "127.0.0.1",
  "BrokerPort": 8321,
  "BrokerPollIntervalSeconds": 5,
  "BrokerMaxConcurrentRuns": 2,
  "BrokerRecoveryPolicy": "skip",
  "BrokerDatabase": ".micro_x/broker.db",
  "BrokerApiSecret": "${BROKER_API_SECRET}",
  "BrokerChannels": {
    "whatsapp": {
      "enabled": true,
      "mode": "polling",
      "poll_interval": 10,
      "trigger_filter": { "chat_ids": ["120363xxx@g.us"] }
    },
    "telegram": {
      "enabled": true,
      "mode": "polling",
      "poll_interval": 5,
      "bot_token": "${TELEGRAM_BOT_TOKEN}",
      "trigger_filter": {}
    },
    "http": {
      "enabled": true,
      "auth_secret": "${BROKER_HTTP_SECRET}"
    }
  }
}
```

## Risks and Mitigations

1. **Broker process management complexity** — Mitigation: atomic PID file + CLI start/stop; auto-start optional.
2. **Webhook security (public endpoints)** — Mitigation: loopback-only by default; per-channel auth verification.
3. **Agent subprocess failure handling** — Mitigation: default timeout + status tracking in broker_runs; explicit failure records.
4. **Response routing reliability** — Mitigation: log all responses; fallback to log if channel unreachable; track delivery status per run.
5. **Misconfigured trigger filter processes unintended messages** — Mitigation: warn on empty filter at startup for messaging channels.

## What This Intentionally Does NOT Do

- No WebSocket streaming protocol — triggers are async, results are collected on completion
- No multi-client live session sharing — single-user tool (but architecture is designed to evolve toward it)
- No runner process isolation — agent runs are trusted local processes
- No warm MCP connection pooling — tool search keeps cold start cost low
- No gateway-style policy engine — simple per-job config is sufficient

These capabilities are documented in the [original gateway plan](PLAN-openclaw-like-gateway-architecture.md) and can be revisited if use cases emerge. The multi-client API direction is documented in [DESIGN-trigger-broker-phase2.md](../design/DESIGN-trigger-broker-phase2.md).

## Future Direction: Multi-Client API

The broker's HTTP server and channel adapter pattern are designed as the foundation for a future multi-client API where any frontend can drive the agent:

| Phase 2 (current) | Future multi-client |
|---|---|
| `POST /api/trigger/{channel}` — fire-and-forget | `POST /api/run` — interactive session start |
| `GET /api/runs/{run_id}` — status query | `WS /api/run/{run_id}/stream` — live streaming |
| `ChannelAdapter` (ingress/egress) | `ClientAdapter` (adds streaming) |
| Subprocess dispatch (results on completion) | In-process execution (streaming during run) |

See [DESIGN-trigger-broker-phase2.md](../design/DESIGN-trigger-broker-phase2.md) for the full analysis.

## Success Criteria

- Cron jobs run reliably on schedule with configurable prompts and sessions.
- External triggers (WhatsApp, Telegram, HTTP) dispatch agent runs and route responses.
- Broker is lightweight — minimal resource usage when idle.
- Agent code requires minimal changes — broker is an orchestration layer, not an agent rewrite.
- Single-process CLI mode remains the default and is unaffected.

## Related Documents

- [DESIGN-trigger-broker.md](../design/DESIGN-trigger-broker.md) — Phase 1 component design
- [DESIGN-trigger-broker-phase2.md](../design/DESIGN-trigger-broker-phase2.md) — Phase 2 architecture with channel adapters and multi-client considerations
- [ADR-018](../architecture/decisions/ADR-018-trigger-broker-subprocess-dispatch.md) — Subprocess dispatch decision record
- [Trigger Broker Operations](../operations/trigger-broker.md) — Setup and usage guide
