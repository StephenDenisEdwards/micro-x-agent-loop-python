# DESIGN: Agent API Server — Multi-Client Architecture

## Problem Statement

The agent is currently tightly coupled to the CLI. All output goes to stdout via `print()`, input comes from `input()` or `--run` args, and the REPL loop lives in `__main__.py`. This prevents non-CLI clients (web apps, desktop apps, mobile apps) from using the agent.

To support multiple client platforms (web, desktop, Android, iOS) alongside the existing CLI, we need an API server that exposes the agent's capabilities over HTTP/WebSocket while keeping the CLI as a first-class client.

## Architecture

```
                           ┌──────────────────────┐
                           │   Agent API Server    │
                           │   (FastAPI + WS)      │
                           │                       │
   Web app  ──HTTP/WS──→  │  ┌─────────────────┐  │
   Desktop  ──HTTP/WS──→  │  │  AgentManager    │  │  ←── AppConfig (shared)
   Android  ──HTTP/WS──→  │  │  (pool of agent  │  │  ←── MCP connections (shared)
   iOS      ──HTTP/WS──→  │  │   instances)     │  │
                           │  └────────┬────────┘  │
   CLI      ──in-process──→  Agent    │            │
                           │          ↓            │
                           │  ┌─────────────────┐  │
                           │  │  StreamBridge    │  │
                           │  │  (routes tokens  │  │
                           │  │   to client)     │  │
                           │  └─────────────────┘  │
                           └──────────────────────┘
```

### Key Principles

1. **The CLI remains a first-class client.** It can use the agent in-process (as today) or connect to a running server. No functionality lost.
2. **The server is the thick layer.** It owns MCP connections, sessions, memory, and agent lifecycle. Clients are thin renderers.
3. **Streaming is via WebSocket.** Text deltas, tool status, and metrics flow in real-time to connected clients.
4. **Sessions are server-side.** Clients identify themselves with a session ID. The server manages persistence.
5. **The broker converges with the server.** The broker's webhook server evolves into the full API server, not a separate process.

## Component Design

### 1. StreamBridge — Decoupling Output from stdout

**The core problem:** The Anthropic provider prints text deltas directly to stdout (`print(event.delta.text, end="", flush=True)`). The TurnEngine has no streaming callback — text goes straight to the terminal.

**Solution:** Introduce a `StreamBridge` protocol that replaces all `print()` calls in the streaming path:

```python
class StreamBridge(Protocol):
    """Routes agent output to the appropriate client."""

    def emit_text_delta(self, text: str) -> None:
        """Called for each text token from the LLM stream."""
        ...

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        """Called when a tool begins execution."""
        ...

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        """Called when a tool finishes execution."""
        ...

    def emit_status(self, message: str) -> None:
        """Called for system status messages (e.g., compaction, max_tokens retry)."""
        ...

    def emit_metric(self, metric: dict) -> None:
        """Called for structured metrics (cost, tokens, timing)."""
        ...
```

**Implementations:**

| Implementation | Client | Behaviour |
|----------------|--------|-----------|
| `TerminalStreamBridge` | CLI | Prints to stdout with spinner coordination (current behaviour) |
| `WebSocketStreamBridge` | Web/mobile | Sends JSON frames over WebSocket |
| `BufferedStreamBridge` | HTTP REST | Accumulates text, returns complete response |
| `NullStreamBridge` | Tests | Discards output |

**Integration points to modify:**
- `anthropic_provider.py:91` — `print(event.delta.text)` → `stream_bridge.emit_text_delta(delta)`
- `openai_provider.py` — same pattern
- `turn_engine.py:116-120` — status messages → `stream_bridge.emit_status()`
- `llm_client.py` — spinner logic moves into `TerminalStreamBridge`
- `agent.py` — line_prefix handling moves into `TerminalStreamBridge`

### 2. AgentManager — Agent Lifecycle for Server Context

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
        stream_bridge: StreamBridge | None = None,
    ) -> Agent: ...

    async def get_or_create_agent(
        self,
        session_id: str,
        stream_bridge: StreamBridge | None = None,
    ) -> Agent: ...

    async def destroy_agent(self, session_id: str) -> None: ...
```

**Design decisions:**

- **MCP connections are shared.** MCP servers are expensive to start (Node.js subprocesses). The AgentManager holds one McpManager, and all agents share the same tool proxies. MCP tool proxies are stateless (each call is independent), so this is safe.
- **Memory store is shared.** One SQLite connection, multiple sessions. Already thread-safe (WAL mode + busy timeout).
- **Agents are per-session.** Each active conversation gets its own Agent instance with its own message history. Idle agents can be evicted after a timeout.
- **StreamBridge is per-request.** Each WebSocket connection or HTTP request gets its own bridge instance.

### 3. API Endpoints

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

**WebSocket message protocol:**

```jsonc
// Client → Server
{"type": "message", "text": "What is 2+2?"}
{"type": "cancel"}                              // Cancel current turn

// Server → Client
{"type": "text_delta", "text": "The answer"}    // Streaming token
{"type": "tool_started", "tool": "read_file"}   // Tool execution status
{"type": "tool_completed", "tool": "read_file", "error": false}
{"type": "status", "message": "Compacting..."}  // System status
{"type": "turn_complete", "usage": {...}}        // Turn finished
{"type": "error", "message": "..."}             // Error
{"type": "question", "id": "...", "text": "..."} // HITL question
```

### 4. CLI as Client

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
- Receives `question` frames and prompts for input via `ask_user`

### 5. Broker Convergence

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
  │                          │──stream_chat()──────────→    │
  │                          │                              │
  │   ←──{"type":            │   ←──text_delta──────────    │
  │       "text_delta",      │                              │
  │       "text":"Hi"}       │                              │
  │                          │                              │
  │   ←──{"type":            │   ←──tool_use────────────    │
  │       "tool_started",    │                              │
  │       "tool":"read"}     │                              │
  │                          │──tool.execute()              │
  │   ←──{"type":            │                              │
  │       "tool_completed"}  │                              │
  │                          │──stream_chat() (continue)──→ │
  │   ←──{"type":            │   ←──text_delta──────────    │
  │       "text_delta",      │                              │
  │       "text":"Done"}     │                              │
  │                          │                              │
  │   ←──{"type":            │                              │
  │       "turn_complete",   │                              │
  │       "usage":{...}}     │                              │
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
