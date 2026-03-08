# API Server Operations

Guide for running and configuring the Agent API Server for web, desktop, and mobile clients.

## Prerequisites

- Python 3.11+ with the agent installed (`pip install -e .` or `uv pip install -e .`)
- A working `config.json` (or variant) with at least one LLM provider configured
- `.env` file with API keys
- (Optional) `fastapi` and `uvicorn` — already bundled as dependencies

## Quick Start

### 1. Start the server

```bash
python -m micro_x_agent_loop --server start
```

The server starts on `127.0.0.1:8321` by default.

### 2. Test the health endpoint

```bash
curl http://localhost:8321/api/health
```

```json
{"status": "ok", "active_sessions": 0, "tools": 5, "memory_enabled": true}
```

### 3. Send a chat message

```bash
curl -X POST http://localhost:8321/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2+2?"}'
```

```json
{"session_id": "abc-123", "response": "2 + 2 = 4", "errors": null}
```

## Configuration

The server is configured via environment variables (in `.env` or shell):

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `127.0.0.1` | Bind address |
| `SERVER_PORT` | `8321` | Listen port |
| `SERVER_API_SECRET` | _(none)_ | Bearer token for authentication. If set, all endpoints except `/api/health` require `Authorization: Bearer <secret>` |
| `SERVER_MAX_SESSIONS` | `10` | Maximum concurrent agent sessions |
| `SERVER_SESSION_TIMEOUT_MINUTES` | `30` | Idle session eviction timeout |

The server loads the same `config.json` as the CLI. Use `--config path` to specify a different config file:

```bash
python -m micro_x_agent_loop --config config-server.json --server start
```

## Authentication

When `SERVER_API_SECRET` is set, all API requests (except `/api/health` and `/docs`) require a Bearer token:

```bash
curl -H "Authorization: Bearer my-secret" http://localhost:8321/api/sessions
```

Unauthenticated requests receive a `401 Unauthorized` response.

## API Endpoints

### Health

```
GET /api/health
```

Returns server status, active session count, tool count, and memory status. No authentication required.

### Sessions

```
POST   /api/sessions                Create a new session (requires memory enabled)
GET    /api/sessions                List sessions (up to 50)
GET    /api/sessions/{id}           Get session details
DELETE /api/sessions/{id}           Delete session and evict agent
GET    /api/sessions/{id}/messages  Get message history for a session
```

### Chat (Non-Streaming)

```
POST /api/chat
```

**Request body:**
```json
{
  "message": "Your prompt here",
  "session_id": "optional-session-id"
}
```

If `session_id` is omitted, a new session is created automatically. Returns the complete response after all tool calls and LLM turns finish.

**Response:**
```json
{
  "session_id": "abc-123",
  "response": "The agent's response text",
  "errors": null
}
```

### WebSocket (Streaming)

```
WS /api/ws/{session_id}
```

Connect via WebSocket for real-time streaming. The server sends JSON frames as the agent processes:

#### Client → Server messages

```jsonc
// Send a user message
{"type": "message", "text": "What is 2+2?"}

// Answer a human-in-the-loop question
{"type": "answer", "question_id": "q1", "text": "Use PDF format"}

// Keepalive ping
{"type": "ping"}
```

#### Server → Client messages

```jsonc
// Streaming text token
{"type": "text_delta", "text": "The answer"}

// Tool execution started
{"type": "tool_started", "tool_use_id": "t1", "tool": "read_file"}

// Tool execution completed
{"type": "tool_completed", "tool_use_id": "t1", "tool": "read_file", "error": false}

// Turn finished with usage metrics
{"type": "turn_complete", "usage": {"input_tokens": 100, "output_tokens": 50}}

// Error occurred
{"type": "error", "message": "Something went wrong"}

// Human-in-the-loop question (agent needs input)
{"type": "question", "id": "q1", "text": "Which format?", "options": [{"label": "PDF"}, {"label": "HTML"}]}

// Keepalive pong
{"type": "pong"}
```

#### WebSocket example (Python)

```python
import asyncio
import websockets
import json

async def chat():
    async with websockets.connect("ws://localhost:8321/api/ws/my-session") as ws:
        await ws.send(json.dumps({"type": "message", "text": "Hello!"}))

        async for msg in ws:
            data = json.loads(msg)
            if data["type"] == "text_delta":
                print(data["text"], end="", flush=True)
            elif data["type"] == "turn_complete":
                print()  # newline after response
                break

asyncio.run(chat())
```

## Interactive API Docs

FastAPI auto-generates interactive API documentation at:

```
http://localhost:8321/docs
```

## Session Lifecycle

1. **Creation** — Sessions are created explicitly via `POST /api/sessions` or implicitly when calling `POST /api/chat` without a `session_id`.
2. **Active** — Each session has an Agent instance with its own message history. WebSocket connections bind to a session.
3. **Eviction** — Sessions idle longer than `SERVER_SESSION_TIMEOUT_MINUTES` are evicted. If the maximum number of sessions (`SERVER_MAX_SESSIONS`) is reached, the oldest idle session is evicted to make room.
4. **Deletion** — `DELETE /api/sessions/{id}` explicitly destroys a session and its agent.
5. **Shutdown** — When the server stops, all active agents are shut down gracefully.

## Architecture

The server shares the same infrastructure as the CLI:

- **MCP connections** — Started once at server startup, shared across all agent sessions
- **Memory store** — Single SQLite connection, multiple sessions (WAL mode)
- **Config** — Loaded once from `config.json` at startup

```
Client (web/mobile/desktop)
    │
    ├── HTTP ──→ POST /api/chat ──→ BufferedChannel ──→ Agent ──→ LLM
    │
    └── WS ───→ /api/ws/{id} ──→ WebSocketChannel ──→ Agent ──→ LLM
                                        ↕
                                  ask_user question/answer
```

## Troubleshooting

### Server hangs on startup

The server starts all configured MCP servers during startup. If an MCP server fails to start (missing Node.js, missing build, etc.), the server will hang. Check:

```bash
# Verify MCP servers are built
ls mcp_servers/ts/packages/*/dist/index.js
```

### Connection refused

Verify the server is running and the port matches:

```bash
curl http://localhost:8321/api/health
```

If using a non-default port, set `SERVER_PORT` in `.env`.

### 401 Unauthorized

If `SERVER_API_SECRET` is set, include the Bearer token in your request:

```bash
curl -H "Authorization: Bearer your-secret" http://localhost:8321/api/sessions
```

### WebSocket disconnects immediately

Check that the session ID is valid and the server is not at capacity. The server logs WebSocket connect/disconnect events.
