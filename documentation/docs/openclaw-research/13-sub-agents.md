# Sub-Agents

Sub-agents are background agent runs spawned from an existing run. They execute in their own session and announce results back to the requester chat.

## How they work

1. Main agent calls `sessions_spawn` with a task description
2. Sub-agent runs in its own session (`agent:<agentId>:subagent:<uuid>`)
3. When finished, an announce step posts a summary back to the requester channel
4. `sessions_spawn` returns immediately (non-blocking): `{ status: "accepted", runId, childSessionKey }`

## Nested sub-agents (orchestrator pattern)

Configurable nesting depth (`maxSpawnDepth`, default 1):

| Depth | Role | Can spawn? |
|-------|------|------------|
| 0 | Main agent | Always |
| 1 | Sub-agent (orchestrator if depth 2 allowed) | Only if `maxSpawnDepth >= 2` |
| 2 | Sub-sub-agent (leaf worker) | Never |

Results flow back up: depth-2 -> announces to depth-1 -> announces to main -> delivers to user.

## Tool policy by depth

- **Depth 1 (leaf, default)**: all tools except session tools (`sessions_list`, `sessions_history`, `sessions_send`, `sessions_spawn`)
- **Depth 1 (orchestrator, when `maxSpawnDepth >= 2`)**: additionally gets `sessions_spawn`, `subagents`, `sessions_list`, `sessions_history`
- **Depth 2 (leaf)**: no session tools, cannot spawn

## Concurrency and limits

- Dedicated queue lane: `subagent`
- `maxConcurrent` (default 8) — global concurrency cap
- `maxChildrenPerAgent` (default 5) — per-session active children cap
- Maximum nesting depth: 5 (range 1-5, recommended: 2)

## Context

Sub-agents only inject `AGENTS.md` + `TOOLS.md` (no SOUL.md, IDENTITY.md, USER.md, HEARTBEAT.md, BOOTSTRAP.md) to keep context small.

## Model and thinking

- Default: inherits from caller
- Override via `agents.defaults.subagents.model` / `.thinking`
- Explicit `sessions_spawn.model` / `.thinking` wins

## Announce format

Normalized template:
- `Status:` derived from runtime outcome (success/error/timeout/unknown)
- `Result:` summary from the announce step
- `Notes:` error details
- Stats: runtime, token usage, estimated cost, sessionKey, transcript path

If sub-agent replies `ANNOUNCE_SKIP`, nothing is posted.

## Cascade stop

- `/stop` in main chat stops all depth-1 agents and cascades to depth-2
- `/subagents kill <id>` stops specific sub-agent and cascades
- `/subagents kill all` stops all sub-agents for the requester

## Auto-archive

Sub-agent sessions archived after `archiveAfterMinutes` (default 60). Transcript renamed to `*.deleted.<timestamp>`.

## Key references

- Sub-agents: [`docs/tools/subagents.md`](/root/openclaw/docs/tools/subagents.md)
- Agent send: [`docs/tools/agent-send.md`](/root/openclaw/docs/tools/agent-send.md)
