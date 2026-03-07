# ADR-018: Trigger Broker with Subprocess Dispatch

## Status

Accepted (extended 2026-03-07 with Phase 2a decisions)

## Context

The agent needed an always-on mechanism to dispatch runs on cron schedules and (in future) from external triggers like webhooks and messaging channels. The original plan ([PLAN-openclaw-like-gateway-architecture.md](../../planning/PLAN-openclaw-like-gateway-architecture.md)) proposed a full gateway daemon with WebSocket transport, warm MCP connection pooling, runner process isolation, and multi-client session sharing.

After analysis, most gateway capabilities solve problems we don't have:

- **Live session sharing** — single-user tool, no concurrent clients
- **Warm MCP connections** — tool search means only needed servers start; cold-start cost is proportional to tools used
- **Mid-run interactive control** — cron and messaging triggers are async/fire-and-forget
- **Sub-second follow-up latency** — WhatsApp/email are inherently async

The core requirement is simpler: a thin always-on layer that receives triggers and spawns agent runs.

Options considered:

1. **Full gateway daemon** (OpenClaw-style) — WebSocket protocol, runner workers, connection pooling
2. **In-process agent execution** — broker imports and calls agent directly in the same process
3. **Subprocess dispatch** — broker spawns `python -m micro_x_agent_loop --run "prompt"` as a child process

## Decision

Adopt **subprocess dispatch** (option 3) for the trigger broker.

The broker is a lightweight daemon that:
- Manages cron schedules via an in-process polling loop with croniter
- Dispatches agent runs as separate Python subprocesses using `asyncio.create_subprocess_exec`
- Tracks job definitions and run history in a dedicated SQLite database (`.micro_x/broker.db`)
- Uses PID-file locking to prevent multiple broker instances
- Handles graceful shutdown via signal handlers (SIGINT/SIGTERM)

Subprocess dispatch was chosen over in-process execution because:
- **Isolation** — a crashed agent run cannot take down the broker
- **Resource cleanup** — subprocess exit guarantees all MCP connections, file handles, and memory are released
- **Simplicity** — no need to manage agent lifecycle, reset state, or handle re-entrant initialization
- **Existing infrastructure** — the `--run` flag and autonomous mode already exist; the broker just orchestrates them

## Phase 2a Extension: Channel Adapters and Webhook Ingress (2026-03-07)

Phase 2a added webhook ingress, response routing, and the channel adapter pattern. Key decisions:

### Channel Adapter Protocol

All external channels (HTTP, WhatsApp, Telegram, email) implement the same `ChannelAdapter` protocol for both ingress and egress. This was chosen over per-channel bespoke integrations because:

- **Uniform dispatch** — the `RunDispatcher` doesn't need to know which channel triggered the run
- **Future multi-client direction** — the adapter pattern extends naturally to `ClientAdapter` with streaming support
- **Testability** — adapters are small, independent units with a clear protocol

### Unified Trigger Filtering

All messaging channels use the same `TriggerFilter` mechanism (`chat_ids`, `sender_ids`, `prefix`) rather than per-channel filtering logic. This was a deliberate design correction — the initial design treated WhatsApp and Telegram differently, but the filtering problem is identical across channels. Making it a config concern (not a channel concern) means adding a new messaging channel requires zero filtering code.

### FastAPI for Webhook Server

FastAPI was chosen for the webhook server over alternatives (aiohttp, raw asyncio HTTP) because:

- **Already available** as a dependency (used by MCP servers in the ecosystem)
- **OpenAPI generation** — useful for future multi-client API documentation
- **URL path parameters** — `POST /api/trigger/{channel}` maps naturally to channel routing
- **Minimal overhead** — runs as a uvicorn server inside the broker's asyncio event loop

The `/api/` URL prefix was chosen to reserve namespace for the future multi-client API (`/api/run`, `/api/run/{id}/stream`).

### Response Router with Fallback

Completed run results are routed through a `ResponseRouter` that:

1. Attempts delivery via the configured channel adapter
2. Falls back to `LogAdapter` if the channel fails
3. Records delivery status (`response_sent`, `response_error`) on each run record

This ensures no result is silently lost, even if the egress channel is temporarily unavailable.

### RunDispatcher as Shared Component

Run dispatch was extracted from the scheduler into a standalone `RunDispatcher` used by both cron scheduling and webhook triggers. This avoids duplicating concurrency management, subprocess spawning, and response routing logic.

## Consequences

### Easier

- Agent code requires zero changes — the broker is purely an orchestration layer
- Each run gets a clean process with no leaked state from previous runs
- Broker stays lightweight and stable — no LLM SDK, no MCP connections, minimal memory footprint
- Adding new trigger sources (webhooks, message polling) only requires a new `ChannelAdapter` implementation
- Response routing is decoupled from dispatch — any channel can route results without dispatcher changes

### Harder

- Cold-start cost per run — each subprocess pays Python startup + MCP connection overhead (mitigated by tool search limiting which servers start)
- No stdout streaming to the broker during execution — results are collected on completion only
- Inter-run state sharing limited to SQLite (session persistence) — no in-memory continuity between runs
- Debugging requires correlating broker logs with subprocess output
