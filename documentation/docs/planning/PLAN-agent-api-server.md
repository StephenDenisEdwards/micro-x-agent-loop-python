# PLAN: Agent API Server — Multi-Client Support

**Status:** Draft
**Created:** 2026-03-07
**Design:** [DESIGN-agent-api-server.md](../design/DESIGN-agent-api-server.md)

## Goal

Enable web, desktop, and mobile clients to interact with the agent via an HTTP/WebSocket API server. The CLI remains a first-class client, either in-process (current) or as a thin client connecting to the server.

## Phased Rollout

### Phase 1: StreamBridge — Decouple Output from stdout

**Scope:** Extract all `print()` calls from the streaming path into a `StreamBridge` protocol. No server yet — just the abstraction that makes one possible.

**Deliverables:**
- [ ] `StreamBridge` protocol in `src/micro_x_agent_loop/stream_bridge.py`
- [ ] `TerminalStreamBridge` — reimplements current stdout + spinner behaviour
- [ ] `BufferedStreamBridge` — accumulates output into a string (for `--run` mode and tests)
- [ ] `NullStreamBridge` — discards output (for tests)
- [ ] Modify `anthropic_provider.py` — accept `StreamBridge`, emit `text_delta` instead of `print()`
- [ ] Modify `openai_provider.py` — same
- [ ] Modify `turn_engine.py` — pass `StreamBridge` through; status messages via `emit_status()`
- [ ] Modify `agent.py` — inject `StreamBridge`; remove `line_prefix` from Agent (move to `TerminalStreamBridge`)
- [ ] Move spinner logic from `llm_client.py` into `TerminalStreamBridge`
- [ ] All existing tests pass with no output changes
- [ ] `--run` mode uses `BufferedStreamBridge` (captures output for broker subprocess IPC)

**Risk:** This touches the core streaming path. Every provider, the turn engine, and the agent need modification. Must be done carefully with full test coverage.

**Estimated complexity:** Medium-high. Many files touched, but each change is mechanical (replace `print()` with `bridge.emit_*()`).

### Phase 2: API Server Foundation

**Scope:** FastAPI server with REST endpoints and WebSocket streaming. Single-user, single-process.

**Prerequisites:** Phase 1 complete.

**Deliverables:**
- [ ] `src/micro_x_agent_loop/server/` package
- [ ] `server/app.py` — FastAPI application with CORS, auth middleware
- [ ] `server/agent_manager.py` — creates/caches/evicts Agent instances per session
- [ ] `server/ws_bridge.py` — `WebSocketStreamBridge` implementation
- [ ] REST endpoints:
  - [ ] `POST /api/chat` — send message, return complete response (non-streaming)
  - [ ] `POST /api/sessions` — create session
  - [ ] `GET /api/sessions` — list sessions
  - [ ] `GET /api/sessions/{id}` — session details
  - [ ] `DELETE /api/sessions/{id}` — end session
  - [ ] `GET /api/sessions/{id}/messages` — message history
  - [ ] `GET /api/health` — health check
- [ ] WebSocket endpoint:
  - [ ] `WS /api/ws/{session_id}` — streaming chat
  - [ ] JSON message protocol (text_delta, tool_started, tool_completed, turn_complete, error)
  - [ ] Turn cancellation via `{"type": "cancel"}`
- [ ] CLI flag: `--server start` to launch the server
- [ ] Bearer token auth (reuse broker pattern)
- [ ] Session timeout and eviction

**Decisions to make:**
- Agent pool size limit (how many concurrent sessions?)
- Session timeout policy (evict after N minutes idle?)
- Should HITL questions route through WebSocket to the connected client?

### Phase 3: Broker Convergence

**Scope:** Merge the broker's webhook server into the API server. One process serves both interactive clients and scheduled/triggered runs.

**Prerequisites:** Phase 2 complete.

**Deliverables:**
- [ ] Migrate broker webhook routes into the API server
- [ ] Broker endpoints (`/api/trigger`, `/api/jobs`, `/api/runs`) coexist with chat endpoints
- [ ] Scheduler runs inside the API server process (no separate broker daemon)
- [ ] In-process agent dispatch option (AgentManager) alongside subprocess dispatch
- [ ] `--broker start` becomes `--server start` (backwards-compatible alias)
- [ ] HITL questions route to WebSocket if client is connected, else to channel adapter
- [ ] Unified health endpoint showing both server and broker status

### Phase 4: CLI as Server Client

**Scope:** The CLI can connect to a running API server instead of running the agent in-process.

**Prerequisites:** Phase 2 complete.

**Deliverables:**
- [ ] `--server http://host:port` flag — CLI connects as WebSocket client
- [ ] Streaming output via WebSocket → terminal (with spinner, line prefix)
- [ ] HITL questions received via WebSocket → terminal `ask_user` prompt
- [ ] Session management commands (`/session list`, `/session resume`) work via REST API
- [ ] Fallback: if server is unreachable, offer to run in-process

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
| `websockets` | WebSocket support in FastAPI | Bundled with FastAPI |
| `httpx` | HTTP client (for CLI-as-client mode) | Yes |

## Architecture Decisions

### Why WebSocket over SSE?

- **Bidirectional:** Client can send cancel signals mid-stream. SSE is server→client only.
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
| **Streaming** | Native (StreamBridge) | Not available (stdout capture) |
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
