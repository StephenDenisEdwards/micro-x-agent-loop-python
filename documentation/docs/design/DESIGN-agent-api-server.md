# DESIGN: Agent API Server — Multi-Client Architecture

## Status

**Implemented** — all 5 phases shipped (`AgentChannel`, FastAPI server, broker convergence, CLI client, SDK). Start with `python -m micro_x_agent_loop --server start`; connect the CLI with `--server http://host:port`. See [API Server Operations](../operations/api-server.md) and [WebSocket Protocol](DESIGN-websocket-protocol.md). The "Problem Statement" below is the original motivation; sections written in future/proposal tense describe decisions that are now in place.

## Problem Statement

The agent is currently tightly coupled to the CLI. All output goes to stdout via `print()`, input comes from `input()` or `--run` args, and the REPL loop lives in `__main__.py`. This prevents non-CLI clients (web apps, desktop apps, mobile apps) from using the agent.

To support multiple client platforms (web, desktop, Android, iOS) alongside the existing CLI, we need:
1. A **bidirectional protocol** between the agent core and any client
2. An **API server** that exposes this protocol over HTTP/WebSocket

## Architecture

```
                           ┌──────────────────────────┐
                           │    Agent API Server       │
                           │    (FastAPI + WS)         │
                           │                           │
   Web app  ──HTTP/WS──→  │  ┌───────────────────┐    │
   Desktop  ──HTTP/WS──→  │  │   AgentManager     │   │  ←── AppConfig (shared)
   Android  ──HTTP/WS──→  │  │   (pool of agent   │   │  ←── MCP connections (shared)
   iOS      ──HTTP/WS──→  │  │    instances)       │   │
                           │  └────────┬──────────┘    │
                           │           │               │
                           │  ┌────────▼──────────┐    │
                           │  │   AgentChannel     │   │
                           │  │   (bidirectional   │   │
                           │  │    protocol)       │   │
                           │  └───────────────────┘    │
                           └──────────────────────────┘

   CLI      ──in-process──→  Agent + TerminalChannel
```

### Key Principles

1. **The CLI remains a first-class client.** It can use the agent in-process (as today) or connect to a running server. No functionality lost.
2. **The server is the thick layer.** It owns MCP connections, sessions, memory, and agent lifecycle. Clients are thin renderers.
3. **Streaming is via WebSocket.** Text deltas, tool status, and metrics flow in real-time to connected clients.
4. **Sessions are server-side.** Clients identify themselves with a session ID. The server manages persistence.
5. **The broker converges with the server.** The broker's webhook server evolves into the full API server, not a separate process.

## Component Design

### 1. AgentChannel — Bidirectional Agent-Client Protocol

The core abstraction. Replaces all direct `print()` calls, `input()` calls, `AskUserHandler`, and `BrokerAskUserHandler` with a single bidirectional protocol.

#### What flows through the channel

**Agent → Client (output):**

| Event | Data | Purpose |
|-------|------|---------|
| `text_delta` | `text: str` | LLM streaming token |
| `tool_started` | `tool_use_id: str, tool_name: str` | Tool execution begins (clients show spinner/indicator) |
| `tool_completed` | `tool_use_id: str, tool_name: str, is_error: bool` | Tool execution ends (clients hide spinner/indicator) |
| `turn_complete` | `usage: dict` | Turn finished, cost/token metrics |
| `error` | `message: str` | Error occurred |

**Agent → Client → Agent (bidirectional):**

| Event | Data | Purpose |
|-------|------|---------|
| `ask_user` | `question: str, options: list[dict] | None` → returns `str` | Human-in-the-loop questioning |

**Client → Agent (input):**

| Event | Data | Purpose |
|-------|------|---------|
| `message` | `text: str` | User prompt |
| `answer` | `answer: str` | Response to `ask_user` |
| `cancel` | — | Cancel current turn |

#### Protocol definition

```python
class AgentChannel(Protocol):
    """Bidirectional communication between agent core and any client."""

    # Agent → Client
    def emit_text_delta(self, text: str) -> None: ...
    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...
    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...
    def emit_turn_complete(self, usage: dict) -> None: ...
    def emit_error(self, message: str) -> None: ...

    # Agent → Client → Agent (blocking/awaitable)
    async def ask_user(self, question: str, options: list[dict] | None = None) -> str: ...
```

Note: `receive_message()` and `cancel_turn()` are not part of the protocol — they are handled by the REPL loop (CLI) or the WebSocket handler (server), which call `agent.run()` and manage cancellation externally.

#### Implementations

| Implementation | Client | How it works |
|----------------|--------|-------------|
| `TerminalChannel` | CLI (in-process) | `print()` for output, `input()` via questionary for `ask_user`, spinner on `tool_started`/`tool_completed` |
| `WebSocketChannel` | Web/desktop/mobile | JSON frames over FastAPI WebSocket. `ask_user` sends question frame, awaits answer frame |
| `BrokerChannel` | Cron/scheduled runs | HTTP POST question to broker API, polls for answer (existing HITL pattern) |
| `BufferedChannel` | Tests / `--run` mode | Accumulates text output into string buffer. `ask_user` returns timeout/default |

#### What each implementation absorbs

The `AgentChannel` replaces several existing components:

| Current component | Absorbed into |
|-------------------|---------------|
| `AskUserHandler` (terminal `ask_user`) | `TerminalChannel.ask_user()` |
| `BrokerAskUserHandler` (HTTP polling `ask_user`) | `BrokerChannel.ask_user()` |
| `Spinner` class in `llm_client.py` | `TerminalChannel` (private implementation detail) |
| `line_prefix` logic in `Agent` | `TerminalChannel` (decides whether to prefix output) |
| `print()` calls in providers | Replaced by `channel.emit_text_delta()` |
| `print()` calls in turn engine | Replaced by `channel.emit_tool_started()` etc. |

#### UI concerns stay in the channel implementation

The spinner is a terminal UI concern. The protocol does not have `show_spinner()` or `hide_spinner()`. Instead:

- `TerminalChannel` starts a spinner when it receives `emit_tool_started()` and stops it on `emit_tool_completed()` or `emit_text_delta()`
- `WebSocketChannel` sends `{"type": "tool_started"}` — the web client decides how to render it (CSS animation, progress bar, etc.)
- `BufferedChannel` ignores tool lifecycle events entirely

Each client is responsible for its own UI presentation. The protocol provides the events; the client decides the rendering.

### 2. Integration Points — What Changes in the Agent Core

#### Provider (anthropic_provider.py, openai_provider.py)

Current:
```python
print(event.delta.text, end="", flush=True)
```

After:
```python
channel.emit_text_delta(event.delta.text)
```

The provider receives the channel (or a callback) from the TurnEngine. The provider's `stream_chat()` signature gains a channel parameter.

#### TurnEngine (turn_engine.py)

The TurnEngine owns the channel reference. It:
- Passes the channel to the provider for `stream_chat()`
- Calls `channel.emit_tool_started()` / `channel.emit_tool_completed()` during tool execution
- Calls `channel.emit_turn_complete()` at end of turn

The existing `TurnEvents` protocol (for memory, metrics, checkpoints) remains separate — `TurnEvents` is for internal bookkeeping, `AgentChannel` is for client communication.

#### Agent (agent.py)

- Receives `AgentChannel` via `AgentConfig` (injected at construction)
- Passes it to `TurnEngine`
- `ask_user` calls go through `channel.ask_user()` instead of `self._ask_user_handler.handle()`
- `_LINE_PREFIX`, `_line_prefix`, spinner coordination all move to `TerminalChannel`

#### Bootstrap (bootstrap.py)

- `bootstrap_runtime()` creates the appropriate channel based on context:
  - Interactive CLI → `TerminalChannel`
  - Autonomous `--run` → `BufferedChannel`
  - Autonomous + HITL → `BrokerChannel`
- Channel is injected into `AgentConfig`

### 3. AgentManager — Agent Lifecycle for Server Context

In CLI mode, one Agent lives for the entire process. In server mode, we need to manage multiple concurrent agents.

```python
class AgentManager:
    """Manages agent instances for the API server."""

    def __init__(
        self,
        app_config: AppConfig,
        mcp_manager: McpManager,
        memory_store: MemoryStore,
    ) -> None: ...

    async def create_agent(
        self,
        session_id: str | None = None,
        channel: AgentChannel | None = None,
    ) -> Agent: ...

    async def get_or_create_agent(
        self,
        session_id: str,
        channel: AgentChannel | None = None,
    ) -> Agent: ...

    async def destroy_agent(self, session_id: str) -> None: ...
```

**Design decisions:**

- **MCP connections are shared.** MCP servers are expensive to start (Node.js subprocesses). The AgentManager holds one McpManager, and all agents share the same tool proxies. MCP tool proxies are stateless (each call is independent), so this is safe.
- **Memory store is shared.** One SQLite connection, multiple sessions. Already thread-safe (WAL mode + busy timeout).
- **Agents are per-session.** Each active conversation gets its own Agent instance with its own message history. Idle agents can be evicted after a timeout.
- **Channel is per-connection.** Each WebSocket connection gets its own `WebSocketChannel` instance, bound to one agent.

### 4. API Endpoints

Built on FastAPI (already a dependency for the broker webhook server).

#### REST Endpoints

```
POST   /api/chat                    Send a message, get a complete response
POST   /api/sessions                Create a new session
GET    /api/sessions                List sessions
GET    /api/sessions/{id}           Get session details
DELETE /api/sessions/{id}           End a session
GET    /api/sessions/{id}/messages  Get message history
GET    /api/health                  Server health check
GET    /api/config                  Current config (non-sensitive)
```

#### WebSocket Endpoint

```
WS     /api/ws/{session_id}         Streaming chat connection
```

**WebSocket message protocol (JSON frames):**

```jsonc
// Client → Server
{"type": "message", "text": "What is 2+2?"}
{"type": "answer", "question_id": "q1", "text": "Use PDF format"}
{"type": "cancel"}

// Server → Client
{"type": "text_delta", "text": "The answer"}
{"type": "tool_started", "tool_use_id": "t1", "tool": "read_file"}
{"type": "tool_completed", "tool_use_id": "t1", "tool": "read_file", "error": false}
{"type": "turn_complete", "usage": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01}}
{"type": "error", "message": "..."}
{"type": "question", "id": "q1", "text": "What format?", "options": [...]}
```

### 5. CLI as Client

The CLI gains a `--server` flag:

```bash
# Direct mode (current, no server needed)
python -m micro_x_agent_loop

# Server mode (connects to running API server)
python -m micro_x_agent_loop --server http://localhost:8321

# Start the server
python -m micro_x_agent_loop --server start
```

In server mode, the CLI becomes a thin WebSocket client:
- Sends user input as `{"type": "message", "text": "..."}`
- Receives `text_delta` frames and prints them with the `assistant> ` prefix
- Receives `tool_started`/`tool_completed` and shows spinner
- Receives `question` frames and prompts for input via terminal `ask_user`

### 6. Broker Convergence

The broker's webhook server and the agent API server converge into one process:

```
Agent API Server (FastAPI)
├── /api/chat, /api/ws/{id}         ← New: client-facing endpoints
├── /api/sessions, /api/health      ← New: session management
├── /api/trigger/{channel}          ← Existing: webhook triggers
├── /api/jobs, /api/runs            ← Existing: broker management
└── /api/runs/{id}/questions        ← Existing: HITL
```

The key difference from the current broker: instead of dispatching agent runs as subprocesses (`--run`), the server can run agents **in-process** using the AgentManager. Subprocess dispatch remains available for isolation when needed.

| Mode | When to use |
|------|-------------|
| In-process (AgentManager) | Interactive clients, low-latency, streaming needed |
| Subprocess (`--run`) | Cron jobs, untrusted prompts, resource isolation |

## Data Flow: WebSocket Chat

```
Client                     Server                      LLM Provider
  │                          │                              │
  │──{"type":"message",──→   │                              │
  │   "text":"hello"}        │                              │
  │                          │──stream_chat(channel)────→   │
  │                          │                              │
  │   ←──{"type":            │   ←──text_delta──────────    │
  │       "text_delta",      │     channel.emit_text_delta()│
  │       "text":"Hi"}       │                              │
  │                          │                              │
  │   ←──{"type":            │   ←──tool_use────────────    │
  │       "tool_started",    │     channel.emit_tool_started()
  │       "tool":"read"}     │                              │
  │                          │──tool.execute()              │
  │   ←──{"type":            │     channel.emit_tool_completed()
  │       "tool_completed"}  │                              │
  │                          │──stream_chat(channel)────→   │
  │   ←──{"type":            │   ←──text_delta──────────    │
  │       "text_delta",      │                              │
  │       "text":"Done"}     │                              │
  │                          │                              │
  │   ←──{"type":            │     channel.emit_turn_complete()
  │       "turn_complete",   │                              │
  │       "usage":{...}}     │                              │
```

## Data Flow: Human-in-the-Loop (ask_user)

```
Client                     Server                      Agent
  │                          │                           │
  │                          │   ←── channel.ask_user()  │  (agent suspends)
  │   ←──{"type":"question", │                           │
  │       "id":"q1",         │                           │
  │       "text":"Format?"} │                           │
  │                          │                           │
  │──{"type":"answer",───→   │                           │
  │   "question_id":"q1",   │──── returns "PDF" ────→   │  (agent resumes)
  │   "text":"PDF"}          │                           │
```

## Security Considerations

- **Authentication:** Bearer token auth (existing pattern from broker). Multi-user support would need per-user tokens and session isolation.
- **Rate limiting:** Per-client rate limits to prevent abuse.
- **Session isolation:** Each session's messages and memory are scoped by session ID. One client cannot access another's session.
- **MCP tool access:** All clients share the same MCP tools. If per-client tool restrictions are needed, that's a future enhancement.
- **CORS:** Server must allow cross-origin requests for web clients.

## Configuration

```json
{
    "ServerEnabled": true,
    "ServerHost": "127.0.0.1",
    "ServerPort": 8321,
    "ServerApiSecret": "${SERVER_API_SECRET}",
    "ServerMaxConcurrentSessions": 10,
    "ServerSessionTimeoutMinutes": 30,
    "ServerCorsOrigins": ["http://localhost:3000"]
}
```

## What This Does NOT Cover

- **Client implementation details** — Each client app (web, desktop, mobile) is a separate project. This design covers only the server-side API they connect to.
- **Multi-user / multi-tenant** — Initial design is single-user (one API key, one set of MCP servers). Multi-tenant would require per-user config, tool isolation, and auth.
- **Horizontal scaling** — Single-process server. MCP servers are subprocesses tied to one host. Scaling requires MCP connection pooling or remote MCP.
- **Persistent WebSocket reconnection** — If the client disconnects mid-turn, the turn continues but output is lost. Reconnection with replay is a future enhancement.

## Related Documents

- [PLAN-agent-api-server.md](../planning/PLAN-agent-api-server.md) — Implementation plan with phased rollout
- [ADR-018](../architecture/decisions/ADR-018-trigger-broker-subprocess-dispatch.md) — Subprocess dispatch decision (broker)
- [DESIGN-trigger-broker.md](DESIGN-trigger-broker.md) — Broker webhook server (converges with API server)
