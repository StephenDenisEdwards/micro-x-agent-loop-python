# System Prompt and Context

## What "context" means

Context is **everything OpenClaw sends to the model for a run**, bounded by the model's context window:
- System prompt (OpenClaw-built)
- Conversation history (user + assistant messages)
- Tool calls/results + attachments (images, audio, file reads)

Context is not the same as "memory" — memory is stored on disk and reloaded; context is what's in the current window.

## System prompt structure

The prompt is OpenClaw-owned, rebuilt each run, and intentionally compact:

1. **Tooling** — current tool list + short descriptions
2. **Safety** — guardrail reminder (advisory, not enforcement)
3. **Skills** — compact list with file paths (model reads SKILL.md on demand)
4. **OpenClaw Self-Update** — how to run `config.apply` and `update.run`
5. **Workspace** — working directory path
6. **Documentation** — local docs path + public mirror
7. **Workspace Files (injected)** — bootstrap files included below
8. **Sandbox** (when enabled) — sandbox paths, elevated exec availability
9. **Current Date & Time** — timezone only (no dynamic clock, for cache stability)
10. **Reply Tags** — optional reply tag syntax
11. **Heartbeats** — heartbeat prompt and ack behavior
12. **Runtime** — host, OS, node, model, repo root, thinking level
13. **Reasoning** — visibility level + toggle hint

## Prompt modes

- `full` (default) — all sections
- `minimal` — for sub-agents; omits Skills, Memory Recall, Self-Update, Model Aliases, User Identity, Reply Tags, Messaging, Silent Replies, Heartbeats
- `none` — base identity line only

## Workspace bootstrap injection

Files injected under **Project Context** on every turn:
- `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `BOOTSTRAP.md`
- `MEMORY.md` (when present; private sessions only)

Limits:
- Per-file: `bootstrapMaxChars` (default 20,000)
- Total: `bootstrapTotalMaxChars` (default 24,000)
- Missing files get a short marker

Sub-agents only inject `AGENTS.md` + `TOOLS.md`.

Internal hooks can intercept via `agent:bootstrap` to mutate files.

## What counts toward the context window

Everything the model receives:
- System prompt (all sections)
- Conversation history
- Tool calls + results
- Attachments/transcripts
- Compaction summaries and pruning artifacts
- Provider wrappers/hidden headers
- **Tool schemas** (JSON sent to model for tool calling — counts even though invisible)

## Two tool costs

1. **Tool list text** in the system prompt
2. **Tool schemas** (JSON) — sent to the model, not visible as text but counts toward context

## Inspecting context

- `/status` — how full is the window
- `/context list` — injected files + rough sizes
- `/context detail` — per-file, per-tool schema, per-skill entry sizes
- `/usage tokens` — per-reply usage footer
- `/compact` — summarize older history to free space

## Key references

- System prompt: [`docs/concepts/system-prompt.md`](/root/openclaw/docs/concepts/system-prompt.md)
- Context: [`docs/concepts/context.md`](/root/openclaw/docs/concepts/context.md)
- Compaction: [`docs/concepts/compaction.md`](/root/openclaw/docs/concepts/compaction.md)
- Session pruning: [`docs/concepts/session-pruning.md`](/root/openclaw/docs/concepts/session-pruning.md)
