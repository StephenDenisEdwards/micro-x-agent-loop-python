# Sub-Agent Architecture Comparison: Claude Code vs. OpenClaw

**Date:** 2026-02-26
**Status:** Complete
**Subject:** Deep comparison of how Claude Code and OpenClaw design, spawn, isolate, and manage sub-agents -- with analysis of trade-offs and lessons for micro-x

---

## 1. Executive Summary

Claude Code and OpenClaw both support delegating work to sub-agents, but they come from opposite design philosophies:

- **Claude Code** treats sub-agents as **short-lived, disposable specialists** -- lightweight, role-typed, context-isolated, one level deep. The parent orchestrates; sub-agents execute and return a summary.
- **OpenClaw** treats sub-agents as **autonomous background workers** -- asynchronous, potentially nested, with their own session lifecycle, concurrency controls, and channel-based result delivery. Sub-agents are closer to independent processes than function calls.

---

## 2. Spawn Mechanism

### Claude Code

The parent agent calls the built-in **`Task`** tool with a `subagent_type`, `prompt`, and optional `model` override. The SDK spawns a new agent instance (either foreground-blocking or background) and returns a summary when complete.

```
Parent → Task(subagent_type="Explore", prompt="Find all API endpoints") → Summary ← Sub-agent
```

Key properties:
- **Synchronous by default** -- parent blocks until sub-agent finishes (foreground mode)
- **Optional background mode** -- parent continues working; notified on completion
- **Resumable** -- sub-agent returns an `agentId` that can be passed to `resume` for follow-up work
- The Task tool is a regular tool call within the agent loop -- no special protocol

### OpenClaw

The parent calls **`sessions_spawn`** with a task description, model override, and optional thinking config. The call returns **immediately** with `{ status: "accepted", runId, childSessionKey }`. The sub-agent runs asynchronously in its own session.

```
Parent → sessions_spawn(task) → { runId, childSessionKey } (immediate)
                                     ↓
                              Sub-agent runs in background
                                     ↓
                              Announce step posts summary to requester channel
```

Key properties:
- **Always asynchronous** -- parent never blocks on sub-agent completion
- **Channel-based result delivery** -- results posted back as messages, not tool return values
- **Session-scoped** -- each sub-agent gets its own session key (`agent:<agentId>:subagent:<uuid>`)
- Sub-agent management via dedicated tools: `/subagents`, `/subagents kill <id>`

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Spawn API | `Task` tool (built-in) | `sessions_spawn` tool |
| Return type | Summary (tool result) | Acceptance receipt (runId) |
| Default blocking | Foreground (blocking) | Non-blocking (always async) |
| Background option | Yes (`run_in_background`) | N/A -- always background |
| Resume support | `agentId` + `resume` parameter | Session key for re-entry |

---

## 3. Nesting Depth

### Claude Code: Strictly flat (depth 1)

Sub-agents **cannot spawn their own sub-agents**. The `Task` tool is excluded from sub-agent tool sets. If multi-step orchestration is needed, the parent chains sequential sub-agent calls.

```
Parent ──┬── Sub-agent A (returns)
         ├── Sub-agent B (returns)    ← sequential, parent orchestrates
         └── Sub-agent C (returns)
```

**Rationale:** Simplicity. Prevents runaway agent chains, makes cost/token usage predictable, and avoids complex result-propagation logic.

### OpenClaw: Configurable nesting (depth 1-5, default 1)

`maxSpawnDepth` controls how many levels of delegation are allowed. At depth 1 (default), sub-agents are leaf workers. At depth 2+, intermediate sub-agents become **orchestrators** that can spawn their own children.

```
Parent (depth 0)
├── Orchestrator (depth 1, maxSpawnDepth >= 2)
│   ├── Worker A (depth 2, leaf)
│   └── Worker B (depth 2, leaf)
└── Worker C (depth 1, leaf)
```

Results flow back up the chain: depth-2 announces to depth-1, depth-1 announces to parent.

**Rationale:** Flexibility. Complex tasks (e.g. "research 5 companies and summarize") benefit from an orchestrator that fans out work to leaf agents, then synthesizes results.

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Max nesting | 1 (hard limit) | 5 (configurable, default 1) |
| Orchestrator pattern | Parent only | Any depth-N agent if `maxSpawnDepth > N` |
| Result propagation | Direct (tool result) | Chain of announce steps |
| Runaway risk | None | Mitigated by depth cap + concurrency limits |

---

## 4. Context and Isolation

### Claude Code

Each sub-agent starts with a **completely fresh context window**:
- No parent conversation history
- Only receives the `prompt` parameter from the Task call
- Uses its own system prompt (role-specific, not the parent's full system prompt)
- Only the **summary** flows back to the parent -- full transcript stays isolated

This is aggressive isolation. The sub-agent knows nothing about the parent's prior conversation.

### OpenClaw

Sub-agents receive a **reduced context injection**:
- `AGENTS.md` + `TOOLS.md` are injected (agent capabilities and tool documentation)
- `SOUL.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `BOOTSTRAP.md` are **excluded** (personality, identity, user prefs, heartbeat config)
- Each sub-agent gets its own JSONL session transcript
- Results delivered via announce step (normalized format with status, result, stats)

This is selective isolation. Sub-agents know what tools exist and how agents work, but don't inherit the parent's personality or user preferences.

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Parent history inherited | No | No |
| System prompt | Agent-type-specific (Explore, Plan, etc.) | Reduced bootstrap (AGENTS.md + TOOLS.md only) |
| Personality/identity | None | None (SOUL.md/IDENTITY.md excluded) |
| Tool documentation | Provided via system prompt | Injected via TOOLS.md |
| Result format | Free-form summary (tool result) | Normalized template (status, result, notes, stats) |
| Full transcript access | Parent never sees it | Stored in JSONL, accessible via `/subagents` |

---

## 5. Model Selection

### Claude Code

Model is selected per sub-agent type:

| Agent Type | Default Model | Override? |
|---|---|---|
| Explore | **Haiku** (fixed) | Yes, via `model` parameter |
| Plan | Inherited from parent | Yes |
| general-purpose | Inherited from parent | Yes |
| claude-code-guide | **Haiku** (fixed) | Yes |
| statusline-setup | **Sonnet** (fixed) | Yes |
| Custom agents | Defined in frontmatter/SDK | Yes |

The pattern: **cheap models for read-only tasks, expensive models for reasoning-heavy tasks.**

### OpenClaw

Model selection has three precedence levels:

1. Explicit `sessions_spawn.model` parameter (highest priority)
2. Config default: `agents.defaults.subagents.model`
3. Inherited from caller (lowest priority)

Thinking budget can also be overridden per-spawn via `sessions_spawn.thinking`.

No built-in concept of agent "types" with default models -- it's all configuration.

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Default model | Per agent type (Haiku for read-only, inherit for others) | Inherited from caller |
| Override mechanism | `model` param on Task call | `sessions_spawn.model` or config default |
| Built-in model tiers | Yes (Haiku/Sonnet/Opus per type) | No (uniform, config-driven) |
| Thinking budget | Not configurable per sub-agent | `sessions_spawn.thinking` override |

---

## 6. Tool Access Control

### Claude Code

Tool sets are **hard-coded per agent type** for built-in agents:

| Agent Type | Tools Allowed | Tools Denied |
|---|---|---|
| Explore | Glob, Grep, Read, Bash, WebFetch, WebSearch | Edit, Write, NotebookEdit, **Task** |
| Plan | Same as Explore | Same as Explore |
| general-purpose | All tools | None |
| claude-code-guide | Glob, Grep, Read, WebFetch, WebSearch | Edit, Write, Bash, NotebookEdit, Task |

Custom agents use explicit allowlists via `tools` field in frontmatter or `AgentDefinition.tools` in the SDK.

Critical constraint: **Task is denied for all sub-agents except general-purpose** -- this enforces the no-nesting rule.

### OpenClaw

Tool policy is **depth-based**:

| Depth | Session Tools | Other Tools |
|---|---|---|
| Depth 1 (leaf, default) | Denied (`sessions_list`, `sessions_history`, `sessions_send`, `sessions_spawn`) | All allowed |
| Depth 1 (orchestrator, `maxSpawnDepth >= 2`) | `sessions_spawn`, `subagents`, `sessions_list`, `sessions_history` allowed | All allowed |
| Depth 2 (leaf) | All denied | All allowed |

Additionally, each agent in a multi-agent setup can have per-agent tool overrides:
```json
{ "tools": { "allow": ["read"], "deny": ["exec", "write", "edit"] } }
```

And sandbox mode can further restrict tool execution environments.

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Policy model | Per agent type (hardcoded + custom allowlists) | Per depth level + per-agent overrides |
| Deny granularity | Specific tool names | Tool categories + session tools by depth |
| Spawn prevention | Task tool excluded from sub-agents | Session tools excluded by depth |
| Sandbox layer | Git worktree isolation (optional) | Docker container isolation (configurable) |
| Per-agent override | Custom agents via `tools` field | `agents.list[].tools.allow/deny` |

---

## 7. Concurrency and Limits

### Claude Code

- Multiple sub-agents can run **in parallel** (parent sends multiple Task calls in one response)
- No explicit concurrency cap documented
- `max_turns` parameter limits how many LLM round-trips a sub-agent can make
- No global resource budgeting across sub-agents

### OpenClaw

Explicit concurrency controls at multiple levels:

| Limit | Default | Scope |
|---|---|---|
| `maxConcurrent` | 8 | Global across all sub-agents |
| `maxChildrenPerAgent` | 5 | Per parent session |
| `maxSpawnDepth` | 1 (range 1-5) | Nesting depth |
| Dedicated queue lane | `subagent` | Queue-level isolation |
| `timeoutSeconds` | 600s | Per-agent runtime |

Sub-agents also have automatic lifecycle management:
- **Cascade stop**: stopping the parent cascades to all children (and grandchildren)
- **Auto-archive**: sessions archived after `archiveAfterMinutes` (default 60)

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Concurrent sub-agents | Unlimited (practical) | `maxConcurrent` (8) + `maxChildrenPerAgent` (5) |
| Turn limits | `max_turns` per sub-agent | `timeoutSeconds` per agent |
| Queue isolation | None (in-process) | Dedicated `subagent` queue lane |
| Cascade stop | N/A (foreground blocks, background notifies) | `/stop` cascades to all children |
| Auto-cleanup | Worktree auto-cleanup (if no changes) | Session archived after 60 minutes |

---

## 8. Permission and Security Model

### Claude Code

Sub-agents can override the parent's permission mode:

| Mode | Behavior |
|---|---|
| `default` | Standard permission checking |
| `acceptEdits` | Auto-approve file edits |
| `dontAsk` | Auto-deny permission prompts |
| `bypassPermissions` | Skip all checks (propagates to sub-agents) |
| `plan` | Read-only |

Hooks (`PreToolUse`, `PostToolUse`) fire for sub-agent tool calls too, enabling centralized guardrails.

### OpenClaw

Sub-agent security combines multiple layers:

1. **Tool policy** -- `allow`/`deny` lists per agent
2. **Sandbox mode** -- Docker containers with configurable workspace access (`none`/`ro`/`rw`)
3. **Exec approvals** -- `deny`/`allowlist`/`full` with optional chat-forwarded approval flow
4. **Sandbox scope** -- per-session, per-agent, or shared containers
5. **Network isolation** -- containers have no network by default

The sandbox is particularly notable: sub-agents can run in Docker containers with no network access and read-only workspace mounts, providing OS-level isolation that Claude Code does not offer.

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Permission model | Mode-based (5 modes) + hooks | Multi-layer pipeline (tools + sandbox + approvals) |
| OS-level isolation | None (process-level only) | Docker containers with network/filesystem isolation |
| Approval flow | User prompts via CLI | Chat-forwarded approvals across channels |
| Read-only enforcement | Agent type (Explore, Plan) | Sandbox `workspaceAccess: "ro"` + tool deny lists |
| Guardrail hooks | PreToolUse/PostToolUse (fire for sub-agents) | before_tool_call/after_tool_call per plugin |

---

## 9. Result Delivery

### Claude Code

Results are **synchronous tool returns**:
- Sub-agent produces a free-form summary
- Summary returned as the Task tool's result
- Parent incorporates it into its context immediately
- No structured format -- the sub-agent decides what to summarize

### OpenClaw

Results are **asynchronous announcements**:
- Sub-agent's final output processed through an **announce step**
- Normalized template with structured fields:
  - `Status:` success/error/timeout/unknown
  - `Result:` summary text
  - `Notes:` error details (if any)
  - `Stats:` runtime, token usage, estimated cost, sessionKey, transcript path
- Posted back to the requester's channel as a message
- `ANNOUNCE_SKIP` suppresses the announcement entirely

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Delivery mode | Synchronous tool result | Asynchronous channel message |
| Format | Free-form summary | Normalized template (status, result, notes, stats) |
| Cost tracking | Available in ResultMessage (parent level) | Per-sub-agent in announce stats |
| Suppress option | N/A | `ANNOUNCE_SKIP` |
| Transcript access | Not exposed to parent | Full JSONL accessible via session key |

---

## 10. Custom Agent Definition

### Claude Code

Two methods:

**Filesystem (`.claude/agents/*.md`):**
```markdown
---
name: code-reviewer
description: Expert code reviewer. Use proactively after code changes.
tools: [Read, Glob, Grep]
model: sonnet
permissionMode: plan
---

You are a senior code reviewer...
```

**Programmatic (Claude Agent SDK):**
```python
AgentDefinition(
    description="Expert code reviewer.",
    prompt="You are a code review specialist...",
    tools=["Read", "Grep", "Glob"],
    model="sonnet",
)
```

Auto-delegation: Claude matches tasks to agents based on the `description` field.

### OpenClaw

Agents are defined in the **gateway config** (`config.json5`):
```json5
{
  agents: { list: [
    { id: "researcher", model: "anthropic/claude-sonnet-4-6",
      sandbox: { mode: "all", scope: "agent" },
      tools: { allow: ["read", "exec", "memory_search"], deny: ["write"] }
    }
  ]},
  bindings: [
    { agentId: "researcher", match: { channel: "telegram" } }
  ]
}
```

Each agent has its own workspace, auth profiles, sessions, and memory. Agents are persistent entities, not ephemeral sub-agents.

**Agent-to-agent messaging** (off by default, explicit opt-in):
```json5
{ tools: { agentToAgent: { enabled: true, allow: ["home", "work"] } } }
```

### Comparison

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| Definition format | Markdown frontmatter or SDK dataclass | JSON/JSON5 config |
| System prompt | Markdown body or `prompt` field | Workspace files (SOUL.md, AGENTS.md) |
| Auto-delegation | Via `description` matching | Via channel bindings (deterministic routing) |
| Agent persistence | Ephemeral (per invocation) | Persistent (own workspace, sessions, memory) |
| Agent-to-agent | Not supported | Opt-in messaging between named agents |

---

## 11. Architectural Philosophy

### Claude Code: Function-Call Model

Sub-agents are **synchronous function calls with isolated context**. The parent is the sole orchestrator. Sub-agents are stateless workers that execute a task and return. This maps naturally to tool-use patterns in LLM APIs.

**Strengths:**
- Simple mental model (parent calls function, gets result)
- Predictable cost (no runaway chains)
- Easy to reason about execution flow
- Model-tier optimization (Haiku for cheap tasks, Opus for hard ones)

**Weaknesses:**
- No nesting limits complex orchestration patterns
- No persistent sub-agent identity or memory
- Parent context must absorb all coordination logic
- No structured result format (summary quality depends on the model)

### OpenClaw: Process Model

Sub-agents are **asynchronous background processes with their own lifecycle**. Each has a session, transcript, and identity. The parent fires and forgets; results arrive later via channel messaging. This maps to microservice/actor patterns.

**Strengths:**
- Nesting enables hierarchical task decomposition
- Explicit concurrency controls prevent resource exhaustion
- Docker sandboxing provides real OS-level isolation
- Structured announcements with cost/token tracking
- Persistent sessions enable auditing and replay

**Weaknesses:**
- Complexity (queue lanes, cascade stop, archive management)
- Asynchronous-only makes simple delegation patterns verbose
- No built-in model-tier optimization (all configuration)
- Channel-based result delivery adds latency vs. direct returns

---

## 12. Key Takeaways for micro-x Design

### 1. Start with Claude Code's simplicity, plan for OpenClaw's flexibility

Claude Code's flat, synchronous model covers 90% of sub-agent use cases. Implement this first. Design the abstraction so nesting can be added later (OpenClaw shows the extension path) without breaking the simple case.

### 2. Role-typed agents with default models are a powerful pattern

Claude Code's approach of assigning cheaper models (Haiku) to read-only exploration tasks is a significant cost optimization. micro-x should adopt this: define agent roles with sensible model defaults rather than making everything configurable from day one.

### 3. Context isolation is non-negotiable

Both systems agree: sub-agents must not inherit the parent's full conversation history. The only question is how much bootstrap context to inject. Claude Code's "prompt only" is the most aggressive; OpenClaw's "AGENTS.md + TOOLS.md" provides more orientation. A reasonable middle ground: inject a compact task description plus tool documentation.

### 4. Tool restriction must be explicit, not implicit

Both systems enforce tool access per agent type/depth. micro-x should require explicit tool allowlists for sub-agents rather than defaulting to "inherit everything". This prevents accidental file modifications by exploration agents and blocks spawn recursion.

### 5. Structured result format is worth adopting from OpenClaw

Claude Code's free-form summaries work but make it hard to extract metadata (cost, duration, error status). OpenClaw's normalized announce template (status + result + notes + stats) is a better foundation for observability and debugging.

### 6. Concurrency controls are necessary at scale

Claude Code has no explicit concurrency caps, which works for single-user CLI use. For a system that might run multiple sub-agents across sessions, OpenClaw's `maxConcurrent` + `maxChildrenPerAgent` pattern prevents resource exhaustion. micro-x should include at minimum a global concurrency limit.

### 7. The nesting question: start at 1, cap at 2

Claude Code's restriction to depth 1 is pragmatic for most tasks. OpenClaw's recommendation of depth 2 (orchestrator + leaf workers) enables the most useful multi-agent pattern: fan-out/fan-in. Going beyond depth 2 adds complexity with diminishing returns. micro-x should default to depth 1 with an opt-in depth-2 orchestrator mode.

---

## Sources

- [Claude Code Sub-Agent Architecture](claude-code-subagent-architecture.md) -- companion research doc
- [OpenClaw Sub-Agents](../openclaw-research/13-sub-agents.md)
- [OpenClaw Multi-Agent Routing](../openclaw-research/09-multi-agent.md)
- [OpenClaw Agent Loop](../openclaw-research/04-agent-loop.md)
- [OpenClaw Sessions and Memory](../openclaw-research/05-sessions-and-memory.md)
- [OpenClaw Sandboxing](../openclaw-research/12-sandboxing.md)
- [OpenClaw Exec and Approvals](../openclaw-research/14-exec-and-approvals.md)
- [Framework Comparison](../openclaw-research/22-framework-comparison.md)
- [Claude Agent SDK Architecture](claude-agent-sdk-architecture.md)
