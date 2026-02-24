# Sessions and Memory

## Sessions

### Storage

- **Store file**: `~/.openclaw/agents/<agentId>/sessions/sessions.json` — JSON map of `sessionKey -> { sessionId, updatedAt, displayName, channel, origin, ... }`
- **Transcripts**: `~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl` — append-only JSONL with every message, tool call, result, token usage, cost, timestamps

The gateway owns all session state. UI clients query the gateway, never read files directly.

### Session keys (routing messages to sessions)

**Direct messages** follow `session.dmScope`:
- `main` (default): all DMs share one session — continuity across devices/channels
- `per-peer`: isolated by sender ID
- `per-channel-peer`: isolated by channel + sender (recommended for multi-user)
- `per-account-channel-peer`: isolated by account + channel + sender

**Other key shapes**:
- Group chats: `agent:<agentId>:<channel>:group:<id>` (always isolated)
- Cron jobs: `cron:<jobId>` (fresh each run)
- Webhooks: `hook:<uuid>`
- Nodes: `node-<nodeId>`

`session.identityLinks` maps the same person across channels to one canonical session.

### Session lifecycle

- **Daily reset**: default 4:00 AM local time
- **Idle reset** (optional): sliding `idleMinutes` window; whichever expires first wins
- **Per-type overrides**: `resetByType` for `direct`, `group`, `thread`
- **Per-channel overrides**: `resetByChannel`
- **Manual**: `/new` or `/reset` in chat

### Context management (three layers)

**1. Session pruning** — trims old tool results **in-memory only** before each LLM call (doesn't touch JSONL). TTL-aware (default 5m). Two levels:
- Soft-trim: oversized results get head+tail with `...`
- Hard-clear: replaces entire result with placeholder

**2. Compaction** — summarizes older conversation into a compact summary entry and **persists** in JSONL. Triggered when nearing context window. Can run a silent memory flush first.

**3. `/new` or `/reset`** — full session reset (new session ID, clean history)

## Memory

### File-based memory (source of truth)

Memory is plain Markdown in the agent workspace (`~/.openclaw/workspace/`):

- **`memory/YYYY-MM-DD.md`** — daily log (append-only). Today + yesterday read at session start.
- **`MEMORY.md`** — curated long-term memory. Only loaded in main/private sessions.

The model only "remembers" what's written to disk.

### Automatic memory flush (pre-compaction)

When a session nears auto-compaction, OpenClaw runs a **silent agentic turn** prompting the model to write durable notes before context is summarized away.

- Triggers at `contextWindow - reserveTokensFloor - softThresholdTokens`
- One flush per compaction cycle
- Skipped if workspace is read-only
- Model usually responds with `NO_REPLY` (invisible to user)

### Vector memory search

Two agent tools provided by the memory plugin (`memory-core`):
- **`memory_search`** — semantic search over Markdown chunks (~400 tokens, 80-token overlap)
- **`memory_get`** — reads a specific memory file by path

**Hybrid search**: BM25 keyword relevance + vector similarity with configurable weights (default 70/30 vector/text).

**Index storage**: per-agent SQLite at `~/.openclaw/memory/<agentId>.sqlite`. File watcher marks index dirty on changes (1.5s debounce). Auto-reindexes if embedding provider/model changes.

**Embedding providers** (auto-selected): local GGUF -> OpenAI -> Gemini -> Voyage.

### QMD backend (experimental)

Swaps built-in SQLite indexer for [QMD](https://github.com/tobi/qmd) — a local-first search sidecar combining BM25 + vectors + reranking. Falls back to built-in if QMD fails.

### Session memory search (experimental)

Optionally indexes session transcripts so `memory_search` can recall past conversations. Opt-in, debounced, indexed asynchronously.

## Key references

- Session management: [`docs/concepts/session.md`](/root/openclaw/docs/concepts/session.md)
- Session pruning: [`docs/concepts/session-pruning.md`](/root/openclaw/docs/concepts/session-pruning.md)
- Memory: [`docs/concepts/memory.md`](/root/openclaw/docs/concepts/memory.md)
- Compaction: [`docs/concepts/compaction.md`](/root/openclaw/docs/concepts/compaction.md)
- CLI sessions: [`docs/cli/sessions.md`](/root/openclaw/docs/cli/sessions.md)
- CLI memory: [`docs/cli/memory.md`](/root/openclaw/docs/cli/memory.md)
