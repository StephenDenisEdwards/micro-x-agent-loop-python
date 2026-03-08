# PLAN: Agent API Server — Multi-Client Support

**Status:** In Progress (Phases 1–4 complete)
**Created:** 2026-03-07
**Updated:** 2026-03-08
**Design:** [DESIGN-agent-api-server.md](../design/DESIGN-agent-api-server.md)

## Goal

Enable web, desktop, and mobile clients to interact with the agent via an HTTP/WebSocket API server. The CLI remains a first-class client, either in-process (current) or as a thin client connecting to the server.

## Phased Rollout

### Phase 1: AgentChannel — Bidirectional Agent-Client Protocol ✅

**Status: Completed** (2026-03-08, branch `feature/agent-channel`, merged to master)

**Scope:** Replace all direct `print()` / `input()` / `AskUserHandler` coupling with a single `AgentChannel` protocol. No server yet — just the abstraction that makes one possible. CLI behaviour unchanged.

**What AgentChannel replaces:**

| Current component | Absorbed into |
|-------------------|---------------|
| `print(delta)` in providers | `channel.emit_text_delta()` |
| `print()` in turn_engine (status) | `channel.emit_tool_started()` / `emit_tool_completed()` |
| `AskUserHandler` (terminal ask_user) | `TerminalChannel.ask_user()` |
| `BrokerAskUserHandler` (HTTP HITL) | `BrokerChannel.ask_user()` |
| `Spinner` class in `llm_client.py` | `TerminalChannel` private detail |
| `line_prefix` in Agent | `TerminalChannel` private detail |

**Deliverables:**
- [x] `AgentChannel` protocol in `src/micro_x_agent_loop/agent_channel.py`
- [x] `TerminalChannel` — reimplements current CLI behaviour (spinner, line prefix, questionary ask_user)
- [x] `BufferedChannel` — for `--run` mode and tests (accumulates text, returns timeout on ask_user)
- [x] `BrokerChannel` — for broker HITL runs (HTTP POST + poll for answer)
- [x] `ASK_USER_SCHEMA` moved from `ask_user.py` to `agent_channel.py`
- [x] Modify `anthropic_provider.py` — accept channel, call `emit_text_delta()` instead of `print()`
- [x] Modify `openai_provider.py` — same
- [x] Modify `turn_engine.py` — accept channel, route tool lifecycle and ask_user through it
- [x] Modify `agent.py` — accept channel via `AgentConfig`, remove `_LINE_PREFIX`, `_ask_user_handler`
- [x] Modify `bootstrap.py` — create appropriate channel based on context
- [x] Delete `ask_user.py` (absorbed into `TerminalChannel` + `agent_channel.py`)
- [x] Delete `broker_ask_user.py` (absorbed into `BrokerChannel`)
- [x] Move `Spinner` class into `TerminalChannel`
- [x] All 400 existing tests pass
- [x] New unit tests for BufferedChannel, TerminalChannel, ASK_USER_SCHEMA

**Key design decisions (settled):**
- Protocol is pure Python, framework-agnostic — no FastAPI dependency
- Spinner is a UI concern — `TerminalChannel` shows one on `tool_started`, other channels don't
- `TurnEvents` (memory, metrics, checkpoints) remains separate from `AgentChannel` (client communication)
- Each channel implementation owns its own presentation logic

### Phase 2: API Server Foundation ✅

**Status: Completed** (2026-03-08, branch `feature/api-server`)

**Scope:** FastAPI server with REST endpoints and WebSocket streaming. Single-user, single-process.

**Prerequisites:** Phase 1 complete.

**Deliverables:**
- [x] `src/micro_x_agent_loop/server/` package
- [x] `server/app.py` — FastAPI application with lifespan startup/shutdown, CORS, auth middleware
- [x] `server/agent_manager.py` — creates/caches/evicts Agent instances per session (configurable capacity + timeout)
- [x] `server/ws_channel.py` — `WebSocketChannel` implementation (JSON frames, ask_user via question/answer with timeout)
- [x] REST endpoints:
  - [x] `POST /api/chat` — send message, return complete response (non-streaming, uses BufferedChannel)
  - [x] `POST /api/sessions` — create session
  - [x] `GET /api/sessions` — list sessions
  - [x] `GET /api/sessions/{id}` — session details
  - [x] `DELETE /api/sessions/{id}` — end session
  - [x] `GET /api/sessions/{id}/messages` — message history
  - [x] `GET /api/health` — health check
- [x] WebSocket endpoint:
  - [x] `WS /api/ws/{session_id}` — streaming chat
  - [x] JSON message protocol (text_delta, tool_started, tool_completed, turn_complete, error, question, answer)
  - [ ] Turn cancellation via `{"type": "cancel"}` — deferred to Phase 3/4
- [x] CLI flag: `--server start` to launch the server
- [x] Bearer token auth (Bearer header, skips /api/health and /docs)
- [x] Session timeout and eviction (configurable via env vars)
- [x] 26 server tests (AgentManager, WebSocketChannel, app endpoints, auth, CLI args)

**Decisions made:**
- Agent pool size: configurable via `SERVER_MAX_SESSIONS` env var (default 10)
- Session timeout: configurable via `SERVER_SESSION_TIMEOUT_MINUTES` env var (default 30 min)
- HITL questions: routed through WebSocket to connected client via question/answer frames
- Server config: environment variables (`SERVER_HOST`, `SERVER_PORT`, `SERVER_API_SECRET`, etc.)

### Phase 3: Broker Convergence ✅

**Status: Completed** (2026-03-08, branch `feature/api-server`)

**Scope:** Merge the broker's webhook server into the API server. One process serves both interactive clients and scheduled/triggered runs.

**Prerequisites:** Phase 2 complete.

**Deliverables:**
- [x] `server/broker_routes.py` — APIRouter with broker endpoints extracted from `webhook_server.py`
- [x] Broker endpoints (`/api/trigger`, `/api/jobs`, `/api/runs`, `/api/runs/{id}/questions`) coexist with chat endpoints
- [x] Scheduler, dispatcher, polling ingress run inside the API server lifespan
- [x] `--broker start` launches the unified API server with broker enabled
- [x] `--server start --broker` or `SERVER_BROKER_ENABLED` env var enables broker in server mode
- [x] `--broker stop/status` still work via existing broker CLI
- [x] Unified health endpoint includes broker status (jobs, active runs, channels)
- [x] 10 broker route tests
- [ ] In-process agent dispatch option (AgentManager) alongside subprocess dispatch — deferred
- [ ] HITL questions route to WebSocket if client is connected — deferred

### Phase 4: CLI as Server Client ✅

**Status: Completed** (2026-03-08, branch `feature/api-server`)

**Scope:** The CLI can connect to a running API server instead of running the agent in-process.

**Prerequisites:** Phase 2 complete.

**Deliverables:**
- [x] `server/client.py` — WebSocket CLI client using `websockets` library
- [x] `--server http://host:port` flag — CLI connects as WebSocket client
- [x] Streaming output via WebSocket → `TerminalChannel` (spinner, line prefix)
- [x] HITL questions received via WebSocket → terminal `ask_user` prompt
- [x] `--session` flag works with client mode for session reuse
- [x] Health check on connect, graceful error handling for unreachable servers
- [x] `websockets>=13.0` added to `pyproject.toml`
- [x] 4 client tests
- [ ] Session management commands (`/session list`, `/session resume`) work via REST API — deferred
- [ ] Fallback: if server is unreachable, offer to run in-process — deferred

### Phase 5: Client SDKs and Documentation

**Scope:** Make it easy for client developers to build apps against the API.

**Prerequisites:** Phase 2 stable.

**Deliverables:**
- [ ] OpenAPI spec auto-generated from FastAPI
- [ ] Python client SDK (thin wrapper around httpx + websockets)
- [ ] TypeScript/JavaScript client SDK (for web and React Native)
- [ ] WebSocket protocol documentation
- [ ] Example web client (minimal HTML + JS chat interface)
- [ ] Example integration test using the Python client SDK

## Dependencies

| Dependency | Purpose | Already installed? |
|------------|---------|--------------------|
| `fastapi` | HTTP/WS server framework | Yes (broker uses it) |
| `uvicorn` | ASGI server | Yes (broker uses it) |
| `websockets` | WebSocket client (CLI-as-client) + FastAPI WS | Added in Phase 4 |
| `httpx` | HTTP client (for CLI-as-client and BrokerChannel) | Yes |

## Architecture Decisions

### Why WebSocket over SSE?

- **Bidirectional:** Client can send cancel signals and HITL answers mid-stream. SSE is server→client only.
- **Natural fit:** Chat is inherently bidirectional. WebSocket maps directly to the interaction model.
- **Mobile support:** WebSocket works well on Android and iOS. SSE has quirks on mobile platforms.
- **Existing pattern:** The broker already uses FastAPI which supports WebSocket natively.

### Why not gRPC?

- **Complexity:** gRPC requires protobuf schema management, code generation, and a different client library per platform.
- **Browser support:** gRPC-Web requires a proxy. WebSocket works natively in browsers.
- **Diminishing returns:** The message format is simple JSON. We don't need gRPC's binary efficiency or streaming multiplexing.

### Why converge with the broker?

- **Single process:** One less thing to manage. The broker is already a FastAPI server.
- **Shared resources:** MCP connections, memory store, and config are expensive to duplicate.
- **Unified API:** Clients can manage jobs, trigger runs, and chat — all from one endpoint.
- **HITL synergy:** Broker HITL questions can route to connected WebSocket clients.

### In-process vs subprocess agent dispatch

| | In-process | Subprocess |
|--|-----------|------------|
| **Latency** | Low (no process startup) | Higher (~2-5s startup) |
| **Streaming** | Native (AgentChannel) | Not available (stdout capture) |
| **Isolation** | Shared memory space | Full process isolation |
| **Use case** | Interactive chat | Cron jobs, untrusted prompts |

Both modes coexist. The AgentManager uses in-process for interactive sessions. The scheduler uses subprocess for cron jobs (as today).

## Non-Goals (for now)

- **Multi-user / multi-tenant:** Single user, single API key. Multi-tenant requires per-user config isolation, auth, and billing.
- **Horizontal scaling:** Single process on one host. MCP servers are local subprocesses.
- **WebSocket reconnection with replay:** If the client disconnects mid-turn, output is lost. Replay requires message buffering.
- **Client apps themselves:** The web/desktop/mobile apps are separate projects. This plan covers only the server API they connect to.
- **Model routing:** Directing different prompts to different models is a separate concern (see PLAN-cost-reduction Phase 3).

## Open Questions

1. **Agent pool sizing:** How many concurrent agents can one server support? Bounded by MCP connections (shared), memory (per-agent message history), and LLM API rate limits.
2. **Session affinity vs stateless:** Should the server keep agents warm between turns (faster, uses memory) or recreate per-request (slower, stateless)?
3. **Auth model:** Bearer token is fine for single-user. What's the path to multi-user? OAuth? API keys per user?
4. **Tool sandboxing:** All clients share the same MCP tools. Should the server support per-session tool restrictions?
5. **File access:** MCP filesystem tools operate on the server's filesystem. How do web/mobile clients interact with files?

## Related Plans

| Plan | Relationship |
|------|-------------|
| [Trigger Broker](PLAN-trigger-broker.md) | Phase 3 converges broker into server |
| [End-User Deployment](PLAN-end-user-deployment.md) | Server simplifies deployment (one process to run) |
| [Cost Reduction Phase 3](PLAN-cost-reduction.md) | Model routing integrates at the AgentManager level |
