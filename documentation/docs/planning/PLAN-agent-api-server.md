# PLAN: Agent API Server — Multi-Client Support

**Status:** Draft
**Created:** 2026-03-07
**Design:** [DESIGN-agent-api-server.md](../design/DESIGN-agent-api-server.md)

## Goal

Enable web, desktop, and mobile clients to interact with the agent via an HTTP/WebSocket API server. The CLI remains a first-class client, either in-process (current) or as a thin client connecting to the server.

## Phased Rollout

### Phase 1: AgentChannel — Bidirectional Agent-Client Protocol

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
- [ ] `AgentChannel` protocol in `src/micro_x_agent_loop/agent_channel.py`
  - `emit_text_delta(text)` — LLM streaming token
  - `emit_tool_started(tool_use_id, tool_name)` — tool begins
  - `emit_tool_completed(tool_use_id, tool_name, is_error)` — tool ends
  - `emit_turn_complete(usage)` — turn finished with metrics
  - `emit_error(message)` — error occurred
  - `async ask_user(question, options)` → `str` — HITL question/answer
- [ ] `TerminalChannel` — reimplements current CLI behaviour:
  - `emit_text_delta` → `print(text, end="", flush=True)` with `assistant> ` prefix on first delta
  - `emit_tool_started` → starts spinner (current `Spinner` class, moved here)
  - `emit_tool_completed` → stops spinner
  - `ask_user` → terminal input via questionary (current `AskUserHandler` logic)
- [ ] `BufferedChannel` — for `--run` mode and tests:
  - `emit_text_delta` → accumulates into string buffer
  - `ask_user` → returns timeout/default message
- [ ] `BrokerChannel` — for broker HITL runs:
  - `ask_user` → HTTP POST to broker API + poll for answer (current `BrokerAskUserHandler` logic)
  - Output events are no-ops (subprocess stdout is captured by runner)
- [ ] Modify `anthropic_provider.py` — accept channel, call `emit_text_delta()` instead of `print()`
- [ ] Modify `openai_provider.py` — same
- [ ] Modify `turn_engine.py`:
  - Accept channel reference
  - Call `emit_tool_started()` / `emit_tool_completed()` during tool execution
  - Call `emit_turn_complete()` at end of turn
- [ ] Modify `agent.py`:
  - Accept `AgentChannel` via `AgentConfig`
  - Remove `_LINE_PREFIX`, `_line_prefix`, `_ask_user_handler`
  - Route `ask_user` calls through `channel.ask_user()`
- [ ] Modify `bootstrap.py`:
  - Create appropriate channel based on context (interactive / autonomous / HITL)
  - Inject into `AgentConfig`
- [ ] Delete `ask_user.py` (absorbed into `TerminalChannel`)
- [ ] Delete `broker_ask_user.py` (absorbed into `BrokerChannel`)
- [ ] Move `Spinner` class from `llm_client.py` into `TerminalChannel`
- [ ] All 370 existing tests pass with no output changes
- [ ] New unit tests for each channel implementation

**Risk:** This touches the core streaming path. Every provider, the turn engine, and the agent need modification. Must be done carefully with full test coverage.

**Complexity:** Medium-high. Many files touched, but each change is mechanical — replace `print()` with `channel.emit_*()`, replace `ask_user_handler` with `channel.ask_user()`.

**Key design decisions (settled):**
- Protocol is pure Python, framework-agnostic — no FastAPI dependency
- Spinner is a UI concern — `TerminalChannel` shows one on `tool_started`, other channels don't
- `TurnEvents` (memory, metrics, checkpoints) remains separate from `AgentChannel` (client communication)
- Each channel implementation owns its own presentation logic

### Phase 2: API Server Foundation

**Scope:** FastAPI server with REST endpoints and WebSocket streaming. Single-user, single-process.

**Prerequisites:** Phase 1 complete.

**Deliverables:**
- [ ] `src/micro_x_agent_loop/server/` package
- [ ] `server/app.py` — FastAPI application with CORS, auth middleware
- [ ] `server/agent_manager.py` — creates/caches/evicts Agent instances per session
- [ ] `server/ws_channel.py` — `WebSocketChannel` implementation:
  - `emit_text_delta` → sends `{"type": "text_delta", "text": "..."}` frame
  - `emit_tool_started` → sends `{"type": "tool_started", ...}` frame
  - `ask_user` → sends question frame, awaits answer frame
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
  - [ ] JSON message protocol (text_delta, tool_started, tool_completed, turn_complete, error, question, answer)
  - [ ] Turn cancellation via `{"type": "cancel"}`
- [ ] CLI flag: `--server start` to launch the server
- [ ] Bearer token auth (reuse broker pattern)
- [ ] Session timeout and eviction (configurable)

**Decisions to make:**
- Agent pool size limit (how many concurrent sessions?)
- Session timeout policy (evict after N minutes idle?)
- HITL questions: route through WebSocket to connected client? (likely yes)

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
- [ ] Streaming output via WebSocket → `TerminalChannel` (spinner, line prefix)
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
