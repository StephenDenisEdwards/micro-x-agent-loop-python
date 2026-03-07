# ADR-018: Trigger Broker with Subprocess Dispatch

## Status

Accepted

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

## Consequences

### Easier

- Agent code requires zero changes — the broker is purely an orchestration layer
- Each run gets a clean process with no leaked state from previous runs
- Broker stays lightweight and stable — no LLM SDK, no MCP connections, minimal memory footprint
- Adding new trigger sources (webhooks, message polling) only requires new ingress code, not agent changes

### Harder

- Cold-start cost per run — each subprocess pays Python startup + MCP connection overhead (mitigated by tool search limiting which servers start)
- No stdout streaming to the broker during execution — results are collected on completion only
- Inter-run state sharing limited to SQLite (session persistence) — no in-memory continuity between runs
- Debugging requires correlating broker logs with subprocess output
