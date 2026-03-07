# Design: Trigger Broker Phase 2 — Webhook Ingress + Response Routing

## Overview

Phase 2 adds external trigger sources (HTTP webhooks, messaging channels) and response routing (send results back to the originating channel). The design is informed by a future requirement: any frontend (web app, CLI, WhatsApp, Messenger) should be able to drive the agent as a client.

## Design Principles

1. **Channel adapters are the abstraction.** Every external channel (WhatsApp, Telegram, HTTP, email) implements the same ingress/egress protocol. Adding a new channel = adding a new adapter.
2. **Trigger filtering is a config concern, not a channel concern.** Every messaging channel has the same problem: which messages are agent triggers vs. noise? The adapter config defines the filter (dedicated chat, keyword prefix, sender whitelist). The adapter applies it.
3. **The HTTP server is the embryo of the future API.** FastAPI is chosen because it grows naturally into a full API layer (WebSocket streaming, OpenAPI docs, dependency injection).
4. **Async human-in-the-loop is deferred to Phase 2b.** It requires a subprocess-to-broker communication protocol that doubles the complexity. Ship webhook + response routing first.

## Architecture

```
BrokerService.start()
  |
  +-- Scheduler task (existing cron loop)
  |
  +-- WebhookServer task (NEW)
  |     FastAPI on BrokerHost:BrokerPort
  |     POST /api/trigger/{channel}     -- webhook ingress
  |     POST /api/trigger/http          -- generic HTTP trigger
  |     GET  /api/runs/{run_id}         -- run status query
  |     GET  /api/jobs                  -- job list
  |     GET  /api/health                -- health check
  |
  +-- PollingIngress tasks (NEW, per enabled polling channel)
        WhatsApp message polling
        Telegram bot long-polling
        Email polling (via Gmail MCP)
```

### Request Flow: Webhook Trigger

```
External Service (WhatsApp Cloud API, Telegram, GitHub, etc.)
  |
  | POST /api/trigger/whatsapp
  v
WebhookServer (FastAPI)
  |
  | 1. Verify signature (per-channel)
  | 2. Extract prompt + metadata via ChannelAdapter.parse_webhook()
  | 3. Apply trigger filter (chat_id, prefix, sender whitelist)
  | 4. If not matched → ignore (return 200 OK, no action)
  v
Dispatcher
  |
  | 5. create_run(trigger_source="whatsapp", ...)
  | 6. spawn subprocess via runner.run_agent()
  v
Agent subprocess (autonomous mode)
  |
  | 7. Execute prompt, persist results, exit
  v
ResponseRouter (NEW)
  |
  | 8. Route result via ChannelAdapter.send_response()
  |    whatsapp → send_message via WhatsApp API/MCP
  |    telegram → sendMessage via Telegram Bot API
  |    http     → POST to callback URL
  |    email    → send via Gmail API/MCP
  |    log      → write to broker logs
  v
Done
```

### Request Flow: Polling Trigger

```
PollingIngress (per channel, runs as asyncio task)
  |
  | 1. Poll for new messages (WhatsApp list_messages, Telegram getUpdates, etc.)
  | 2. Apply trigger filter (chat_id, prefix, sender whitelist)
  | 3. For each matched message:
  v
Dispatcher (same as webhook flow from step 5)
```

## Components

### 1. Trigger Filtering

Every messaging channel has the same fundamental problem: not every message is an agent trigger. The filtering logic is unified across all channels via config:

```python
@dataclass
class TriggerFilter:
    """Configurable filter for determining which messages are agent triggers."""
    chat_ids: list[str] | None = None       # Only messages from these chats/groups
    sender_ids: list[str] | None = None     # Only messages from these senders
    prefix: str | None = None               # Only messages starting with this prefix (stripped before use as prompt)

    def matches(self, chat_id: str | None, sender_id: str, text: str) -> str | None:
        """Check if a message matches the filter.

        Returns the prompt text (with prefix stripped) if matched, or None if filtered out.
        """
        ...
```

**Examples:**

Dedicated WhatsApp group for agent commands:
```json
{
  "whatsapp": {
    "enabled": true,
    "mode": "polling",
    "trigger_filter": { "chat_ids": ["120363xxx@g.us"] }
  }
}
```

Any WhatsApp message starting with `/agent`:
```json
{
  "whatsapp": {
    "enabled": true,
    "mode": "polling",
    "trigger_filter": { "prefix": "/agent" }
  }
}
```

Telegram bot (all messages to the bot are triggers — no filter needed):
```json
{
  "telegram": {
    "enabled": true,
    "trigger_filter": {}
  }
}
```

Only specific Telegram users:
```json
{
  "telegram": {
    "enabled": true,
    "trigger_filter": { "sender_ids": ["123456789"] }
  }
}
```

### 2. ChannelAdapter Protocol

The core abstraction. Each channel implements this protocol for both ingress and egress:

```python
class ChannelAdapter(Protocol):
    """Adapter for a messaging/trigger channel."""

    @property
    def channel_name(self) -> str:
        """Channel identifier: 'whatsapp', 'telegram', 'http', 'email'."""
        ...

    @property
    def supports_webhook(self) -> bool:
        """Whether this channel can receive webhook POSTs."""
        ...

    @property
    def supports_polling(self) -> bool:
        """Whether this channel can poll for new messages."""
        ...

    def verify_request(self, headers: dict, body: bytes) -> bool:
        """Verify webhook signature/token. Returns True if valid."""
        ...

    def parse_webhook(self, payload: dict) -> TriggerRequest | None:
        """Extract a trigger request from a webhook payload.

        Returns None if the payload is not actionable (status update, filtered out, etc.).
        The trigger filter is applied internally.
        """
        ...

    async def poll_messages(self) -> list[TriggerRequest]:
        """Poll for new messages and return any that match the trigger filter.

        Called periodically by PollingIngress. Returns empty list if no new triggers.
        """
        ...

    async def send_response(self, target: str, result: RunResult) -> bool:
        """Send a run result back to the originating channel.

        Args:
            target: Channel-specific target (phone number, chat ID, email, URL).
            result: The completed run result.

        Returns True if sent successfully.
        """
        ...
```

```python
@dataclass
class TriggerRequest:
    """Parsed trigger from an external channel."""
    prompt: str                    # The user's message / prompt text (prefix stripped)
    sender_id: str                 # Channel-specific sender (phone, chat ID, email)
    channel: str                   # Channel name
    response_target: str | None = None  # Where to send the result (defaults to sender_id)
    session_id: str | None = None  # Resume a session (if channel supports it)
    metadata: dict | None = None   # Channel-specific metadata (message ID, timestamp, etc.)
```

### 3. Channel Adapters

All messaging adapters support both ingress (triggers) and egress (responses). The mode (webhook vs polling) is a deployment choice, not a channel limitation.

#### WhatsAppAdapter

**Ingress (polling mode):** Polls the existing WhatsApp MCP server's `list_messages` tool.
- Tracks last-seen message timestamp to avoid reprocessing
- Applies trigger filter (chat_id, prefix, sender whitelist)
- Works locally with no public URL or Cloud API account

**Ingress (webhook mode):** WhatsApp Cloud API sends POST to `/api/trigger/whatsapp`.
- Verify using the webhook verify token
- Parse incoming message payload → extract text + sender phone number
- Requires Cloud API account + public URL (or tunnel)

**Egress:** Send message via WhatsApp MCP server's `send_message` tool or Cloud API.
- Formats RunResult.summary as a message (truncated to 4096 char limit)
- Uses sender_id from trigger or response_target from job config

#### TelegramAdapter

**Ingress (polling mode):** Long-poll Telegram Bot API `getUpdates` endpoint.
- Bot created via BotFather — every message to the bot is intentionally for the agent
- Still supports trigger filter for multi-user bots (sender whitelist)
- Tracks update_id offset to avoid reprocessing

**Ingress (webhook mode):** Telegram sends POST to `/api/trigger/telegram`.
- Verify via secret token in header
- Requires public URL (or tunnel)

**Egress:** Call Telegram Bot API `sendMessage` via httpx.
- Uses chat_id from trigger or response_target
- Supports Markdown formatting

#### HttpAdapter (generic)

**Ingress (webhook only):** Direct POST to `/api/trigger/http`.
- Verify via shared secret in `Authorization` header
- JSON payload: `{"prompt": "...", "session_id": "...", "callback_url": "..."}`
- No trigger filter needed — every POST is intentional

**Egress:** POST result to callback URL.
- JSON payload: `{"run_id": "...", "status": "...", "result": "...", "error": "..."}`
- If no callback_url, response is available via `GET /api/runs/{run_id}`

#### EmailAdapter (future)

**Ingress (polling):** Poll Gmail MCP `gmail_search` for messages with a specific label/subject.
**Egress:** Call Gmail MCP `gmail_send` to reply.

Not in initial Phase 2 scope — listed for design completeness.

### 4. WebhookServer

FastAPI application running inside the broker:

```python
class WebhookServer:
    def __init__(
        self,
        store: BrokerStore,
        dispatcher: RunDispatcher,
        adapters: dict[str, ChannelAdapter],
        host: str,
        port: int,
    ) -> None: ...

    async def start(self) -> None:
        """Start the FastAPI server as an asyncio task."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown."""
        ...
```

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Health check (broker status, job count, active runs) |
| POST | `/api/trigger/{channel}` | Webhook ingress (dispatches a run via channel adapter) |
| GET | `/api/runs/{run_id}` | Query run status and result |
| GET | `/api/jobs` | List configured jobs |

The `/api/` prefix reserves URL space for the future multi-client API (`/api/run`, `/api/run/{id}/stream`).

### 5. RunDispatcher

Extracted from the scheduler to be shared between cron dispatch and webhook/polling dispatch:

```python
class RunDispatcher:
    """Dispatches agent runs and routes responses on completion."""

    def __init__(
        self,
        store: BrokerStore,
        response_router: ResponseRouter,
        max_concurrent_runs: int,
    ) -> None: ...

    async def dispatch(
        self,
        *,
        prompt: str,
        trigger_source: str,
        job_id: str | None = None,
        session_id: str | None = None,
        config_profile: str | None = None,
        timeout_seconds: int | None = None,
        response_channel: str = "log",
        response_target: str | None = None,
    ) -> str:
        """Create a run record, spawn the agent, route the response. Returns run_id."""
        ...
```

The scheduler and webhook server both delegate to `RunDispatcher`. This avoids duplicating dispatch + response routing logic.

### 6. ResponseRouter

Routes completed run results to the appropriate channel:

```python
class ResponseRouter:
    def __init__(self, adapters: dict[str, ChannelAdapter]) -> None: ...

    async def route(
        self,
        run_id: str,
        channel: str,
        target: str,
        result: RunResult,
        store: BrokerStore,
    ) -> bool:
        """Route a run result to the specified channel.

        Updates the run record with response delivery status.
        Returns True if sent successfully.
        """
        ...
```

Fallback chain: if the configured channel fails, falls back to `log` and records the error.

### 7. PollingIngress

For channels using polling mode:

```python
class PollingIngress:
    def __init__(
        self,
        adapter: ChannelAdapter,
        dispatcher: RunDispatcher,
        poll_interval: int,
    ) -> None: ...

    async def start(self) -> None:
        """Poll loop: check for new messages, dispatch matching triggers."""
        ...

    def stop(self) -> None: ...
```

Runs as a parallel asyncio task in BrokerService. Each polling adapter has its own task and interval. Uses the same error backoff pattern as the scheduler (consecutive error counter, max backoff).

## Data Model Changes

### broker_runs — new columns

| Column | Type | Purpose |
|--------|------|---------|
| `response_channel` | TEXT | Channel to route response to (from job or trigger) |
| `response_target` | TEXT | Channel-specific target for response |
| `response_sent` | INTEGER DEFAULT 0 | Whether response was successfully sent |
| `response_error` | TEXT | Error if response sending failed |

Ad-hoc webhook triggers set these per-run from the trigger metadata. Cron jobs inherit from `broker_jobs.response_channel` / `response_target`.

### broker_jobs — no schema changes

The existing `response_channel` and `response_target` columns are already defined and sufficient.

## Configuration

```json
{
  "BrokerWebhookEnabled": true,
  "BrokerHost": "127.0.0.1",
  "BrokerPort": 8321,
  "BrokerChannels": {
    "whatsapp": {
      "enabled": true,
      "mode": "polling",
      "poll_interval": 10,
      "api_token": "${WHATSAPP_API_TOKEN}",
      "verify_token": "${WHATSAPP_VERIFY_TOKEN}",
      "trigger_filter": {
        "chat_ids": ["120363xxx@g.us"],
        "prefix": null,
        "sender_ids": null
      }
    },
    "telegram": {
      "enabled": true,
      "mode": "polling",
      "poll_interval": 5,
      "bot_token": "${TELEGRAM_BOT_TOKEN}",
      "trigger_filter": {
        "sender_ids": ["123456789"]
      }
    },
    "http": {
      "enabled": true,
      "auth_secret": "${BROKER_HTTP_SECRET}"
    }
  }
}
```

### Trigger filter fields

| Field | Type | Meaning |
|-------|------|---------|
| `chat_ids` | list or null | Only messages from these chats/groups (WhatsApp group JID, Telegram chat_id) |
| `sender_ids` | list or null | Only messages from these senders (phone number, Telegram user_id) |
| `prefix` | string or null | Only messages starting with this prefix; prefix is stripped from the prompt |

All fields are optional. Omitted or null means "don't filter on this dimension." An empty `trigger_filter` object means "accept all messages" (appropriate for a Telegram bot where every message is intentional).

If multiple fields are set, all must match (AND logic).

## Security

1. **Loopback-only by default** — `BrokerHost: "127.0.0.1"` prevents external access unless explicitly opened.
2. **Per-channel verification** — WhatsApp verify token, Telegram bot token validation, HTTP shared secret.
3. **Trigger filtering** — prevents the agent from processing unintended messages. Misconfigured filters are the operator's responsibility, but sensible defaults (require at least one filter for messaging channels) reduce risk.
4. **No public exposure required for polling mode** — WhatsApp polling and Telegram long-polling work without a public URL.
5. **Rate limiting** — FastAPI middleware limits requests per IP to prevent abuse when webhooks are exposed.

## Future Multi-Client Considerations

This design intentionally leaves room for the full multi-client API:

| Phase 2 (now) | Future multi-client |
|---|---|
| `POST /api/trigger/{channel}` — fire-and-forget | `POST /api/run` — interactive session start |
| `GET /api/runs/{run_id}` — status query | `WS /api/run/{run_id}/stream` — live streaming |
| Response routing via adapters | Streaming via WebSocket adapter |
| Subprocess dispatch (results on completion) | In-process execution (streaming during run) |
| `ChannelAdapter` protocol (ingress/egress) | `ClientAdapter` protocol (adds streaming) |
| `RunDispatcher` (shared dispatch logic) | Same dispatcher, extended with streaming mode |

The adapter pattern is the bridge: a future `WebClientAdapter` or `RemoteCLIAdapter` implements the same protocol with streaming support added.

## Phased Implementation

### Phase 2a: HTTP Trigger + Response Routing + Infrastructure
1. Add FastAPI + uvicorn dependencies
2. Implement `TriggerFilter` dataclass with `matches()` logic
3. Implement `ChannelAdapter` protocol and `TriggerRequest` dataclass
4. Implement `HttpAdapter` (simplest, good for testing the full flow)
5. Implement `WebhookServer` with FastAPI endpoints
6. Implement `ResponseRouter`
7. Extract `RunDispatcher` from scheduler (shared dispatch logic)
8. Wire WebhookServer into `BrokerService.start()` as parallel task
9. Add response columns to `broker_runs` schema
10. Update CLI: `--job add` accepts `--response-channel` and `--response-target`

### Phase 2a+: Messaging Channel Adapters
11. Implement `PollingIngress` loop
12. Implement `WhatsAppAdapter` (polling mode via existing MCP, egress via MCP)
13. Implement `TelegramAdapter` (polling via Bot API, egress via Bot API)

### Phase 2b: Async Human-in-the-Loop — Complete (2026-03-07)

Subprocess-to-broker communication via HTTP for async questioning.

**Components:**

- **`BrokerAskUserHandler`** (`broker/broker_ask_user.py`) — replaces `AskUserHandler` in subprocess runs. POSTs questions to `POST /api/runs/{run_id}/questions`, polls `GET .../questions/{qid}` for answers.
- **`broker_questions` table** — tracks question_text, options, answer, status (pending/answered/timed_out), timeout_at. Auto-timeouts via pre-computed deadline.
- **New endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/runs/{run_id}/questions` | Agent subprocess posts a question |
| GET | `/api/runs/{run_id}/questions/{qid}` | Agent polls for answer |
| POST | `/api/runs/{run_id}/questions/{qid}/answer` | External client/channel posts answer |
| GET | `/api/runs/{run_id}/questions` | List pending questions for a run |

- **`send_question`** on `ChannelAdapter` protocol — routes questions to the originating channel
- **Environment variables** passed to subprocess: `MICRO_X_BROKER_URL`, `MICRO_X_RUN_ID`, `MICRO_X_HITL_TIMEOUT`
- **HITL system prompt** — distinct from autonomous; tells agent it can ask but should be sparing
- **Per-job config:** `hitl_enabled` (bool), `hitl_timeout_seconds` (default 300)
- **CLI:** `--hitl` and `--hitl-timeout` flags on `--job add`

**Flow:**

```
Agent subprocess calls ask_user
  → BrokerAskUserHandler.handle()
    → POST /api/runs/{run_id}/questions (question + options)
    → Broker stores question, routes to channel via send_question
    → Handler polls GET .../questions/{qid} every 3 seconds
    → Answer arrives (via POST .../answer from channel/client)
    → Handler returns answer to agent
    → (or times out → agent gets "no response" message)
```

### Phase 3: Operational Hardening — Complete (2026-03-07)

**Retry policy:**
- Per-job `max_retries` (default 0) and `retry_delay_seconds` (default 60)
- On failure, dispatcher creates a new `queued` run with `attempt_number + 1` and `scheduled_at = now + delay × 2^(attempt-1)`
- Scheduler picks up due retries alongside cron jobs
- CLI: `--max-retries` and `--retry-delay` flags on `--job add`

**Missed-run recovery:**
- On broker start, scheduler scans enabled jobs with `next_run_at` in the past
- Policy `skip` (default): advance schedule to next future occurrence
- Policy `run_once`: leave `next_run_at` in the past — next poll dispatches it
- Config: `BrokerRecoveryPolicy`

**Management endpoint auth:**
- When `BrokerApiSecret` is configured, FastAPI middleware enforces `Authorization: Bearer <secret>` on all endpoints except `/api/health`
- Loopback-only binding remains the primary security measure

## Dependencies to Add

```toml
# pyproject.toml
"fastapi>=0.115.0",
"uvicorn>=0.34.0",
```

Both are lightweight. FastAPI pulls in Starlette and Pydantic (already compatible with the project).

## Risks

| Risk | Mitigation |
|------|-----------|
| Misconfigured trigger filter processes unintended messages | Require at least one filter field for messaging channels; warn on empty filter at startup |
| WhatsApp Cloud API requires business account + public URL | Polling mode is the primary approach; Cloud API webhook is optional |
| Telegram bot token exposure | Store in .env, never log |
| Webhook endpoint abuse | Loopback-only default + rate limiting + per-channel auth |
| Response routing failure (channel down) | Log all responses; retry once; fallback to log channel; record error in run |
| FastAPI adds dependency weight | Minimal — Starlette is small; Pydantic already compatible |
| Polling latency (seconds, not milliseconds) | Acceptable for messaging channels; webhook mode available for lower latency |

## Related Documents

- [PLAN-trigger-broker.md](../planning/PLAN-trigger-broker.md) — feature plan
- [DESIGN-trigger-broker.md](DESIGN-trigger-broker.md) — Phase 1 design
- [ADR-018](../architecture/decisions/ADR-018-trigger-broker-subprocess-dispatch.md) — subprocess dispatch decision
