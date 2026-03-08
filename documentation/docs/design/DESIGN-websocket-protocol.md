# DESIGN: WebSocket Protocol Reference

## Endpoint

```
WS /api/ws/{session_id}
```

Connect with a unique `session_id` to create or resume a session. The server creates an Agent instance for the session and binds it to the WebSocket connection.

If authentication is enabled (`SERVER_API_SECRET`), include the Bearer token as a WebSocket header:

```
Authorization: Bearer <secret>
```

## Message Format

All messages are JSON objects with a `type` field.

## Client → Server Messages

### `message` — Send a user prompt

```json
{
  "type": "message",
  "text": "What is 2+2?"
}
```

Triggers an agent turn. The server streams responses back as events.

### `answer` — Respond to a HITL question

```json
{
  "type": "answer",
  "question_id": "q1",
  "text": "Use PDF format"
}
```

Sent in response to a `question` event from the server. The `question_id` must match.

### `ping` — Keepalive

```json
{
  "type": "ping"
}
```

Server responds with `{"type": "pong"}`. Use for connection keepalive (recommended: every 30s).

## Server → Client Messages

### `text_delta` — Streaming text token

```json
{
  "type": "text_delta",
  "text": "The answer is"
}
```

Emitted as the LLM generates text. Concatenate all `text_delta` events to build the full response. May arrive rapidly — buffer if needed for UI rendering.

### `tool_started` — Tool execution begins

```json
{
  "type": "tool_started",
  "tool_use_id": "toolu_abc123",
  "tool": "filesystem__read_file"
}
```

The agent is executing a tool. Clients should show a loading indicator (spinner, progress bar, etc.).

### `tool_completed` — Tool execution ends

```json
{
  "type": "tool_completed",
  "tool_use_id": "toolu_abc123",
  "tool": "filesystem__read_file",
  "error": false
}
```

The tool finished. `error: true` indicates the tool returned an error result. Clients should hide the loading indicator.

### `turn_complete` — Turn finished

```json
{
  "type": "turn_complete",
  "usage": {
    "input_tokens": 1500,
    "output_tokens": 200,
    "cache_read_tokens": 1000,
    "cost_usd": 0.012
  }
}
```

The agent has finished processing the user's message. The `usage` dict contains token counts and cost metrics. The client can now accept new input.

A single user message may produce multiple `text_delta`, `tool_started`, and `tool_completed` events before the final `turn_complete`.

### `error` — Error occurred

```json
{
  "type": "error",
  "message": "Rate limit exceeded, retrying in 30s"
}
```

An error during processing. The turn may or may not continue after an error.

### `question` — HITL question (agent needs input)

```json
{
  "type": "question",
  "id": "q1",
  "text": "Which file format should I use?",
  "options": [
    {"label": "PDF", "description": "Portable Document Format"},
    {"label": "HTML", "description": "Web page"}
  ]
}
```

The agent is asking the user a clarifying question. The client must:
1. Display the question and options to the user
2. Collect the user's answer
3. Send an `answer` message with the matching `question_id`

If `options` is `null`, the question is free-form text. If options are provided, the user can select one or type a custom answer.

**Timeout:** If no answer is received within the server's HITL timeout (default 300s), the agent receives a timeout message and continues without input.

### `pong` — Keepalive response

```json
{
  "type": "pong"
}
```

Response to a client `ping`.

## Turn Lifecycle

A typical turn flows as follows:

```
Client                          Server
  │                               │
  │── message ──────────────────→ │
  │                               │  (LLM generates response)
  │ ←──────────── text_delta ──── │
  │ ←──────────── text_delta ──── │
  │                               │  (LLM decides to use a tool)
  │ ←──────────── tool_started ── │
  │                               │  (tool executes)
  │ ←──────────── tool_completed  │
  │                               │  (LLM generates more text)
  │ ←──────────── text_delta ──── │
  │ ←──────────── text_delta ──── │
  │ ←──────────── turn_complete ─ │
  │                               │
  │── message ──────────────────→ │  (next turn)
```

## Multi-Turn Tool Calls

The agent may invoke multiple tools in sequence within a single turn. Each tool produces a `tool_started` / `tool_completed` pair. The turn does not end until all tools have completed and the LLM has generated its final response.

```
text_delta* → tool_started → tool_completed → text_delta* → tool_started → tool_completed → text_delta* → turn_complete
```

## Connection Lifecycle

1. **Connect** — Client opens WebSocket to `/api/ws/{session_id}`
2. **Chat** — Client sends `message`, receives streaming events
3. **Reconnect** — If disconnected, reconnect with the same `session_id` to resume the session. Note: events from a turn in progress during disconnection are lost.
4. **Close** — Client closes the WebSocket. The session remains on the server until evicted by timeout or explicit deletion.

## Error Handling

- **401 on connect** — Authentication failed. Check `SERVER_API_SECRET`.
- **1011 close code** — Server not ready (still starting up).
- **Unexpected disconnect** — Reconnect with the same session ID. The agent state is preserved server-side.

## Related

- [API Server Operations](../operations/api-server.md) — REST endpoints and configuration
- [DESIGN-agent-api-server.md](DESIGN-agent-api-server.md) — Architecture overview
