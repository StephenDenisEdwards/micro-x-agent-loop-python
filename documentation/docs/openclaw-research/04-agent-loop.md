# Agent Loop

The agent loop is the full run of an agent: intake -> context assembly -> model inference -> tool execution -> streaming replies -> persistence.

## Lifecycle (end-to-end)

### 1. Entry

A message arrives via Gateway RPC (`agent`/`agent.wait`) or CLI (`openclaw agent`). The gateway validates params, resolves the session, persists metadata, and immediately returns `{ runId, acceptedAt }`.

### 2. Queue serialization

Runs are serialized per session key (session lane) + an optional global lane. This prevents tool/session races and keeps history consistent. Channels choose queue modes:
- **steer** — inbound messages inject mid-run (after each tool call, remaining tool calls are skipped)
- **followup/collect** — messages held until current turn ends, then a new turn starts

### 3. Session + workspace preparation

- Workspace directory resolved (or sandbox workspace for non-main sessions)
- Skills loaded from bundled -> managed -> workspace (workspace wins on name conflict)
- Bootstrap files injected into context: `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `BOOTSTRAP.md`
- Session write lock acquired, `SessionManager` opened
- `agent:bootstrap` hook fires (can mutate bootstrap files)

### 4. Prompt assembly

System prompt built from base prompt + skills prompt + bootstrap context + per-run overrides. Model-specific token limits and compaction reserves enforced.

### 5. Model inference

`runEmbeddedPiAgent` calls into the pi-agent-core runtime. The model thinks, streams assistant deltas, and optionally calls tools.

### 6. Tool execution

Tool start/update/end events emitted on the `tool` stream. Results sanitized for size and image payloads. Messaging tool sends tracked to suppress duplicate confirmations.

### 7. Streaming

Assistant deltas streamed as `assistant` events. Block streaming (off by default) can send completed blocks early with configurable chunking (800-1200 chars, paragraph-aware).

### 8. Reply shaping

- Final payloads assembled from assistant text + optional reasoning + inline tool summaries
- `NO_REPLY` filtered silently
- Messaging tool duplicates removed
- If nothing renderable remains and a tool errored, a fallback error reply emitted

### 9. Compaction

If the session nears the context window, auto-compaction summarizes older history into a compact entry, persists it in JSONL, and retries with compacted context. Can optionally run a silent memory flush first.

### 10. Persistence

Session transcripts stored as JSONL at `~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl`.

## Plugin hook points (in order)

| Hook | When |
|------|------|
| `before_agent_start` | Before the run starts (inject context, override system prompt) |
| `llm_input` | Observe LLM input payload |
| `before_tool_call` | Before each tool call (can block) |
| `after_tool_call` | After each tool call |
| `tool_result_persist` | Synchronously transform tool results before writing to transcript |
| `llm_output` | Observe LLM output |
| `before_compaction` / `after_compaction` | Around compaction cycles |
| `agent_end` | After completion (inspect final messages + metadata) |

## Event streams

Three streams emitted over WebSocket:
- **`lifecycle`** — `phase: "start" | "end" | "error"`
- **`assistant`** — streamed text deltas from the model
- **`tool`** — tool start/update/end events

## Timeouts

- **Agent runtime**: `agents.defaults.timeoutSeconds` (default 600s) — kills the run
- **`agent.wait` RPC**: default 30s — only the wait times out, agent keeps running

## Early termination

- Agent timeout (abort)
- AbortSignal (cancel)
- Gateway disconnect
- `agent.wait` timeout (wait-only, doesn't stop the agent)

## Key references

- Agent loop: [`docs/concepts/agent-loop.md`](/root/openclaw/docs/concepts/agent-loop.md)
- Agent runtime: [`docs/concepts/agent.md`](/root/openclaw/docs/concepts/agent.md)
- Compaction: [`docs/concepts/compaction.md`](/root/openclaw/docs/concepts/compaction.md)
- Queue: [`docs/concepts/queue.md`](/root/openclaw/docs/concepts/queue.md)
- Streaming: [`docs/concepts/streaming.md`](/root/openclaw/docs/concepts/streaming.md)
- System prompt: [`docs/concepts/system-prompt.md`](/root/openclaw/docs/concepts/system-prompt.md)
