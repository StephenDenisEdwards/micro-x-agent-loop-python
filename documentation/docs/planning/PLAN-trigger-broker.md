# Plan: Trigger Broker (Always-On Run Dispatcher)

## Status

**Phase 1 Complete** (2026-03-06) — Replaces [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) at priority #11. Core broker + cron + autonomous mode implemented. Phase 2 (webhooks + response routing) planned.

## Goal

Add a lightweight always-on service that can receive triggers (cron schedules, webhooks, message polling) and dispatch agent runs, routing results back to the originating channel.

## Background and Decision Record

The original plan ([PLAN-openclaw-like-gateway-architecture.md](PLAN-openclaw-like-gateway-architecture.md)) proposed a full OpenClaw-style gateway daemon with WebSocket transport, runner worker isolation, multi-client session sharing, and policy enforcement. After analysis, this was determined to be over-engineered for the actual use cases.

### Use cases driving this work

1. **Scheduled/cron tasks** — run agent jobs on a timer (e.g., daily content publishing, periodic data checks)
2. **Remote control via messaging** — trigger agent runs from WhatsApp, Telegram, email, or other channels

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
                          | - Email response       |
                          | - Log/persist          |
                          | - Webhook callback     |
                          +------------------------+
```

## Components

### 1. Trigger Ingress

Receives or generates run triggers from multiple sources:

- **Cron scheduler** — in-process scheduler (e.g., APScheduler) with timezone-aware cron expressions
- **Webhook endpoints** — HTTP server receiving callbacks from WhatsApp, GitHub, etc.
- **Message polling** — poll-based integrations where webhooks aren't available
- **HTTP API** — manual trigger via `curl` or external tool integration
- **File watcher** — optional: drop a `.prompt` file, broker picks it up

### 2. Run Dispatcher

Spawns agent runs with the right configuration:

- Session ID (resume existing or create new)
- Prompt (from trigger payload or job template)
- Config profile (which MCP servers, model, etc.)
- Timeout and resource limits

Execution model: subprocess or async task — agent runs to completion and exits.

### 3. Response Egress

Routes agent output back to the originating channel:

- WhatsApp reply (via WhatsApp MCP/API)
- Email reply (via Gmail MCP)
- Webhook callback to external service
- Log to file/database for cron jobs
- No-op (fire-and-forget jobs)

### 4. Job/Schedule Store

Persistent storage for scheduled jobs and run history:

- SQLite (extend existing `.micro_x/memory.db` or separate broker DB)
- Job definitions: cron expression, timezone, prompt template, target session, response channel
- Run history: trigger source, start/end time, status, error info

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
| response_channel | TEXT NOT NULL | `whatsapp`, `email`, `log`, `webhook`, `none` |
| response_target | TEXT NULL | Channel-specific target (phone number, email, URL) |
| overlap_policy | TEXT NOT NULL | `skip_if_running`, `queue_one` |
| timeout_seconds | INTEGER NULL | Max run duration |
| created_at | TEXT NOT NULL | ISO 8601 |
| updated_at | TEXT NOT NULL | ISO 8601 |
| last_run_at | TEXT NULL | ISO 8601 |
| next_run_at | TEXT NULL | ISO 8601 |

### `broker_runs`

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| job_id | TEXT NULL | FK to broker_jobs (NULL for ad-hoc triggers) |
| trigger_source | TEXT NOT NULL | `cron`, `whatsapp`, `http`, `file`, etc. |
| prompt | TEXT NOT NULL | Actual prompt sent |
| session_id | TEXT NULL | Session used |
| status | TEXT NOT NULL | `queued`, `running`, `completed`, `failed`, `cancelled`, `skipped` |
| started_at | TEXT NULL | ISO 8601 |
| completed_at | TEXT NULL | ISO 8601 |
| result_summary | TEXT NULL | Brief output or error |
| error_text | TEXT NULL | Error details if failed |

## Trigger Channel Notes

| Channel | Mechanism | Complexity | Notes |
|---------|-----------|------------|-------|
| Cron | In-process scheduler | Low | APScheduler or similar |
| WhatsApp | Webhook or polling via existing MCP | Medium | Needs callback URL or poll loop |
| Telegram | Bot API long-polling | Low | Simpler than WhatsApp, no business account needed |
| Email/Gmail | Polling via Gmail MCP | Low | Already have Gmail MCP server |
| GitHub | Webhook | Low | React to PRs, issues, etc. |
| Slack | Webhook/Events API | Medium | |
| HTTP | Direct POST endpoint | Low | `curl`/external tool integration |
| File watcher | `watchdog` or polling | Low | Drop file in watched directory |

## Human Interaction in Autonomous Runs

The interactive agent uses `ask_user` for human-in-the-loop questioning and mode analysis prompts. Broker-dispatched runs have no human at the keyboard. This requires a strategy for handling situations where the agent would normally ask for input.

### Phase 1: Fully autonomous (no human input)

Broker runs operate in autonomous mode:
- `ask_user` tool is removed from the tool set
- Mode analysis user prompts are disabled
- Voice ingress is disabled
- System prompt includes an autonomy directive: the agent cannot ask questions and must either proceed with its best judgement or report that it cannot continue

Job prompts must be written to be self-contained — if a cron job regularly needs human input, it's a poorly designed job.

**Limitation:** Some tasks genuinely benefit from clarification. A fully autonomous agent may make wrong assumptions or fail where a single question would have unblocked it.

### Phase 2: Asynchronous human-in-the-loop (future)

When webhook ingress and response routing exist (Phase 2), the agent could route questions to the originating channel and wait for a reply:

- Agent calls `ask_user` → broker intercepts and sends the question to the trigger channel (WhatsApp, email, Slack)
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

This is speculative and depends on Phase 2 proving the single-channel pattern works.

## Phased Rollout

### Phase 1: Core Broker + Cron (Low Risk)

- `--run "prompt"` one-shot CLI flag for non-interactive agent execution
- Autonomous mode: strips `ask_user`, disables interactive features, adds autonomy system prompt directive (see "Human Interaction in Autonomous Runs")
- Broker service with cron scheduler
- Agent run dispatch (subprocess via `--run`)
- Job store (SQLite)
- Log-based response egress
- CLI management: `--broker start`, `--broker stop`, `--broker status`
- Job management: `--job add`, `--job list`, `--job remove`, `--job run-now`

Acceptance:
- A cron job triggers at the expected time, runs the agent autonomously, and logs results.
- The agent operates without `ask_user` and does not hang waiting for input.
- Overlap policy is enforced.
- Broker restart preserves job definitions and schedule state.

### Phase 2: Webhook Ingress + Response Routing (Medium Risk)

- HTTP webhook server (lightweight — e.g., aiohttp or FastAPI)
- WhatsApp/Telegram trigger integration
- Response egress routing (reply on originating channel)
- Ad-hoc trigger tracking in broker_runs
- Asynchronous human-in-the-loop: route `ask_user` questions to the trigger channel and wait for reply (see "Human Interaction in Autonomous Runs — Phase 2")

Acceptance:
- A WhatsApp message triggers an agent run and the result is sent back as a reply.
- Multiple trigger channels work independently.
- The agent can ask a question via the trigger channel and resume when answered.

### Phase 3: Operational Hardening (Medium Risk)

- Run timeout and cancellation
- Retry policy with backoff for failed runs
- Health check endpoint
- Missed-run recovery policy after broker downtime (`skip` or `run_once_on_recovery`)
- Basic auth for management endpoints (loopback-only by default)

Acceptance:
- Failed runs retry per policy and emit failure records.
- Broker restart applies recovery policy correctly.
- Stale/hung runs are detected and cancelled.

## Configuration

```json
{
  "BrokerEnabled": true,
  "BrokerHost": "127.0.0.1",
  "BrokerPort": 8321,
  "BrokerPollIntervalSeconds": 5,
  "BrokerMaxConcurrentRuns": 2,
  "BrokerRecoveryPolicy": "skip",
  "BrokerDatabase": ".micro_x/broker.db"
}
```

## Risks and Mitigations

1. **Broker process management complexity** — Mitigation: simple PID file + CLI start/stop; auto-start optional.
2. **Webhook security (public endpoints)** — Mitigation: loopback-only by default; webhook signature verification per channel.
3. **Agent subprocess failure handling** — Mitigation: timeout + status tracking in broker_runs; explicit failure records.
4. **Response routing reliability** — Mitigation: log all responses; retry egress failures; fallback to log if channel unreachable.

## What This Intentionally Does NOT Do

- No WebSocket streaming protocol — triggers are async, results are collected on completion
- No multi-client live session sharing — single-user tool
- No runner process isolation — agent runs are trusted local processes
- No warm MCP connection pooling — tool search keeps cold start cost low
- No gateway-style policy engine — simple per-job config is sufficient

These capabilities are documented in the [original gateway plan](PLAN-openclaw-like-gateway-architecture.md) and can be revisited if use cases emerge.

## Success Criteria

- Cron jobs run reliably on schedule with configurable prompts and sessions.
- External triggers (WhatsApp, webhook, HTTP) dispatch agent runs and route responses.
- Broker is lightweight — minimal resource usage when idle.
- Agent code requires minimal changes — broker is an orchestration layer, not an agent rewrite.
- Single-process CLI mode remains the default and is unaffected.
