# Plan: Sub-Agent Architecture

**Status:** Phase 2b Completed (observability + memory tracking) — Phase 3+ remaining
**Date:** 2026-03-12

### Remaining Gaps

- **Phase 3 (Async)** — `spawn_background_task` via broker not implemented.
- **Phase 4 (Advanced)** — custom agent types, mode selector integration, resume not started.
**Goal:** Enable the main agent to delegate focused tasks to lightweight, disposable sub-agents with isolated contexts, restricted tools, and optionally cheaper models.

---

## 1. Why Sub-Agents?

Sub-agents are not primarily a cost optimisation. The core motivations, drawn from how Claude Code, OpenClaw, OpenAI Agents SDK, and LangGraph implement them:

### Context Window Protection (primary reason)

The main agent's context is precious and finite. Every tool result, search output, and file read consumes context. Sub-agents perform exploratory work — grep through 50 files, search the web, read 10 documents — in a **disposable context** that gets thrown away. Only a summary returns to the parent.

Without sub-agents, a "find where this function is used" task might consume 30K tokens of grep results in the main context. With a sub-agent, it costs ~200 tokens (the summary).

For this project specifically, multi-step tasks with web searches + file reads can blow through 200K tokens in the main context, triggering expensive compaction cycles. Sub-agents keep exploratory noise off the main context entirely.

### Task Isolation / Blast Radius

A sub-agent that goes off the rails (loops, makes bad tool calls, burns tokens) doesn't corrupt the parent's conversation. Claude Code enforces this with **one-level nesting only** — no runaway chains. OpenClaw adds concurrency limits (max 8 concurrent, max 5 children per parent).

### Specialization (role-optimized prompts + tools)

Different tasks need different system prompts and tool sets:
- **Explore** agent: read-only tools, optimized for search, doesn't need Edit/Write
- **Plan** agent: no mutation tools, focused on design reasoning
- **Coding** agent: full tool set but scoped to a specific subtask

Restricting the tool set prevents mistakes — a read-only sub-agent literally cannot overwrite a file.

### Parallelism

The main agent is sequential — it reasons, calls tools, waits, reasons again. Sub-agents enable parallel work: "search for X in the frontend" and "search for X in the backend" simultaneously. OpenClaw leans into this with async spawning. Claude Code supports background agents.

### User Experience

Long-running exploratory work blocks the main agent. With sub-agents, the main agent can report "I've dispatched a search agent, meanwhile..." — the user sees progress rather than silence.

### Cost Reduction (secondary benefit)

Using Haiku for simple research tasks costs ~10x less than Sonnet. This is a valuable side effect of the architecture, not the primary driver.

---

## 2. Orchestration Models: Blocking vs Async

The frameworks use fundamentally different orchestration models for sub-agents. Understanding this distinction is critical for our design.

### Claude Code: Blocking (agents-as-tools)

The parent agent calls a sub-agent and **waits for the result** before continuing. The sub-agent's summary comes back as a tool result in the same turn.

```
Parent turn:
  1. LLM decides to delegate → calls Task tool
  2. Sub-agent runs to completion (parent blocked)
  3. Sub-agent summary returns as tool result
  4. Parent continues reasoning with the result
  5. Parent's turn eventually ends
```

This is the **agents-as-tools** pattern (OpenAI SDK terminology). The parent retains control and uses the result immediately. Sequential reasoning works naturally — "find X, then refactor it" is one parent turn with a sub-agent call in the middle.

### OpenClaw: Async (fire-and-forget to messaging channel)

OpenClaw is fundamentally a **messaging platform** — the user interacts via WhatsApp, Slack, Discord, etc. Sub-agents don't return results to the parent agent. They post results directly to the user's chat.

```
User sends "research X and Y" on WhatsApp
  → Main agent receives message
  → Main agent calls sessions_spawn("research X")
  → Main agent calls sessions_spawn("research Y")
  → sessions_spawn returns immediately: { status: "accepted" }
  → Main agent replies: "I've dispatched two research tasks"
  → Main agent's turn ENDS

  ... time passes ...

  → Sub-agent 1 finishes → announces result to WhatsApp chat
  → Sub-agent 2 finishes → announces result to WhatsApp chat
  → User sees results appear as new messages
```

The parent agent never processes the results — its turn is already over. The **user is the orchestrator** who closes the loop. If synthesis is needed, the user sends a follow-up message.

This works because messaging is inherently asynchronous — users send a message, walk away, and results appear later.

### What this means for complex tasks

Neither model limits the agent's capability for deep reasoning or coding. The main agent handles multi-step reasoning, coding, and tool chains **within its own turn** — it doesn't need sub-agents for this. Sub-agents are for **independent, parallelizable side-quests** that would pollute the main context.

**Good sub-agent tasks** (independent, context-heavy):
- "Research X while I continue working on Y"
- "Search this codebase for all usages of function Z and summarize"
- Fan-out: "Check these 5 repos for security issues"

**Not sub-agent tasks** (sequential, reasoning-dependent):
- "Find where this function is defined and then refactor it" — sequential, stays in the main agent
- "Debug this error" — requires iterative reasoning in one context

### A general-purpose agent needs both

Both patterns serve different needs, and a general-purpose agent benefits from having both:

**Blocking** — when the parent needs the result to continue reasoning:
- "Find all usages of this function" → uses the list to decide what to refactor
- "Search the web for X" → synthesizes findings into a response
- The result feeds directly into the next reasoning step

**Async** — when the work is independent and the user doesn't need to wait:
- "Go research competitors and write a report to my documents folder"
- "Monitor this API endpoint every hour and alert me if it goes down"
- "Analyse all 20 repos and post findings to Slack"

The LLM (or the user) chooses based on whether the result is needed immediately or can arrive later.

### Our phased approach

**Phase 1: Blocking** — in-process sub-agent, result returns as a tool result. The LLM delegates a focused task, gets the summary back, continues reasoning. The user sees one coherent response. This covers the primary use case (context protection for exploratory work).

**Phase 3: Async via broker** — we already have the infrastructure. The trigger broker dispatches subprocess jobs with `--run`, and channel adapters deliver results to WhatsApp, Discord, webhooks, etc. The missing piece is letting the main agent **spawn a broker job mid-conversation** rather than only via cron/webhooks. This would be a `spawn_background_task` tool that creates a broker run, with results delivered through whatever channel adapters are configured. No new async infrastructure needed — just a bridge from the agent's tool dispatch to the broker's job system.

---

## 3. Research References

Extensive research already exists in this codebase:

| Document | Key Insights |
|----------|-------------|
| [Claude Code Sub-Agent Architecture](../research/claude-code-subagent-architecture.md) | Built-in agent types (Explore, Plan, general-purpose), one-level nesting, fresh context per sub-agent, tool set restriction, foreground/background/worktree modes, resume capability |
| [Comparison: Claude Code vs OpenClaw vs OpenAI SDK vs LangGraph](../research/comparison-subagents-claude-code-vs-openclaw.md) | Four-way comparison of spawn mechanisms, blocking vs async, context injection, result delivery, model override, nesting depth |
| [OpenAI Agents SDK Multi-Agent Patterns](../research/openai-agents-sdk-multi-agent-deep-research.md) | Two patterns: handoffs (peer-to-peer, caller yields) vs agents-as-tools (parent retains control, gets summary). Context passing, tracing, MCP integration |
| [LangGraph Multi-Agent Deep Research](../research/langgraph-multi-agent-deep-research.md) | Graph-based composition, supervisor/network/hierarchical patterns, typed state schemas, checkpointing, streaming across agent boundaries |
| [OpenClaw Sub-Agents](../openclaw-research/13-sub-agents.md) | Autonomous background workers, session lifecycle, announce-on-completion, configurable nesting depth (1-5), concurrency controls, context injection (AGENTS.md + TOOLS.md only) |
| [ADR-018: Trigger Broker Subprocess Dispatch](../architecture/decisions/ADR-018-trigger-broker-subprocess-dispatch.md) | Proven subprocess dispatch pattern — reusable for sub-agent spawning |

### Pattern Summary from Research

| Dimension | Claude Code | OpenClaw | OpenAI SDK | This Project (proposed) |
|-----------|-------------|----------|------------|------------------------|
| Spawn mechanism | Task tool | sessions_spawn | Handoffs or agents-as-tools | spawn_subagent pseudo-tool |
| Blocking | Foreground or background | Always async | Handoffs block, tools block | Blocking (Phase 1), async later |
| Nesting | 1 level max | 1-5 (default 1) | Unbounded | 1 level (Phase 1) |
| Context | Fresh window, prompt only | Injects AGENTS.md + TOOLS.md | Full history passed | Fresh window, prompt only |
| Result delivery | Summary to parent | Announce post | Return value | Tool result to parent |
| Model override | Per-agent type | Per-spawn or global | Per-agent | Per-spawn (config defaults) |
| Tool restriction | Per-agent type allowlist | By nesting depth | Per-agent | Per-agent type allowlist |

---

## 4. Current Architecture

### What exists today

The single-agent loop: `Agent` → `TurnEngine` → `Provider` → tool dispatch → repeat.

```
Agent.run(user_message)
  └── TurnEngine.run(messages, user_message)
        └── LOOP:
              ├── Provider.stream_chat(model, messages, tools)
              ├── Execute tool calls (asyncio.gather — parallel)
              ├── Append results to messages
              └── Until stop_reason != "tool_use"
```

### Existing affordances

| Affordance | How it helps |
|------------|-------------|
| **Tool Protocol** | `spawn_subagent` is just another pseudo-tool implementing `Tool`. No TurnEngine changes needed for dispatch. |
| **Async infrastructure** | Agent core is fully async. TurnEngine already does `asyncio.gather()` for parallel tool execution. |
| **AgentChannel Protocol** | Decouples agent from client. Sub-agents could use a `BufferedChannel` or `NullChannel`. |
| **Broker runner** | `broker/runner.py` already demonstrates subprocess dispatch with result capture, timeout enforcement, and environment variable IPC. |
| **Provider abstraction** | Supports multiple models. Creating a second provider for a cheap model is straightforward. |
| **MCP Manager** | Manages MCP server connections. Sub-agents could share warm connections (in-process) or start fresh (subprocess). |
| **Bootstrap** | `bootstrap_runtime()` wires up memory, MCP servers, event sinks. Could create a lightweight variant for sub-agents. |

---

## 5. Design

### 5.1 — In-Process vs Subprocess

| Dimension | In-Process | Subprocess |
|-----------|-----------|------------|
| Cold start | None — reuses warm connections | 3-5s (Python startup + MCP connections) |
| Isolation | Shared process, needs careful state management | Full process isolation |
| MCP connections | Shares parent's warm connections | Must establish own connections |
| Failure blast radius | Can crash parent | Isolated — parent unaffected |
| Complexity | Medium — state isolation, tool filtering | Low — reuse broker/runner.py |
| Cost effectiveness | High — no startup overhead for cheap tasks | Low — cold start defeats cheap model savings |

**Decision: In-process for Phase 1.** The primary use case is quick, focused tasks (search, read, summarize) where subprocess cold-start overhead would exceed the actual work. Subprocess remains available via the existing broker runner for long-running or risky tasks.

### 5.2 — Sub-Agent Types

Following Claude Code's pattern of built-in agent types with pre-configured roles:

| Type | Model | Tools | System Prompt | Use Case |
|------|-------|-------|---------------|----------|
| `explore` | Haiku | Read-only (read_file, bash read commands, web_fetch, web_search, grep, glob) | "You are a research assistant. Find information and return a concise summary." | Codebase search, web research, file reading |
| `summarize` | Haiku | None (LLM-only) | "Summarize the following content concisely." | Distill large content into key points |
| `general` | Inherited from parent | All parent tools | Parent system prompt (trimmed) | Complex subtasks needing full capability |

Additional types can be added later without architectural changes.

### 5.3 — Pseudo-Tool Interface

The main agent calls sub-agents via a `spawn_subagent` pseudo-tool (like `ask_user` and `tool_search`):

```python
# Tool schema presented to the LLM
{
    "name": "spawn_subagent",
    "description": "Delegate a focused task to a sub-agent with its own context window. Use this for exploratory work (searching files, reading docs, web research) to avoid polluting your main context. The sub-agent runs to completion and returns a summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear description of what the sub-agent should do and what to return"
            },
            "type": {
                "type": "string",
                "enum": ["explore", "summarize", "general"],
                "description": "Agent type: 'explore' (cheap, read-only), 'summarize' (cheap, no tools), 'general' (full capability)",
                "default": "explore"
            }
        },
        "required": ["task"]
    }
}
```

### 5.4 — Execution Flow

```
Parent TurnEngine receives tool_use: spawn_subagent
  │
  ├── Create SubAgentRunner with type config (model, tools, prompt)
  ├── Build lightweight Agent instance:
  │     ├── Fresh message list (empty)
  │     ├── Filtered tool set (from type config)
  │     ├── Cheap provider (Haiku) or inherited
  │     ├── Sub-agent system prompt
  │     ├── No memory persistence (disposable)
  │     ├── No compaction (fresh context, won't need it)
  │     └── BufferedChannel (captures output, no terminal IO)
  │
  ├── Run sub-agent: agent.run(task_prompt)
  │     └── TurnEngine loop executes normally
  │           ├── Uses parent's warm MCP connections
  │           ├── Restricted to allowed tools only
  │           └── Runs until completion or timeout
  │
  ├── Collect result:
  │     ├── Final assistant message = sub-agent's answer
  │     ├── Usage metrics aggregated to parent session
  │     └── Sub-agent context discarded
  │
  └── Return ToolResult(text=summary) to parent TurnEngine
```

### 5.5 — Nesting, Interactivity, and Safety

- **One level only** in Phase 1. Sub-agents do not have the `spawn_subagent` tool.
- **No user interaction.** Sub-agents never have `ask_user`. They work autonomously from the task prompt and return a result. If they can't complete the task, they report what they found and what's missing. This matches both Claude Code (autonomous with summary return) and OpenClaw (async, non-blocking, announce-on-completion). The parent agent is the only agent that talks to the user.
- **Timeout**: configurable per-type, default 60 seconds for explore, 120 for general.
- **Token budget**: sub-agent gets its own `MaxTokens` (lower for explore/summarize).
- **Turn limit**: max turns per sub-agent (default 10 for explore, 20 for general) to prevent loops.

### 5.6 — MCP Connection Sharing

In-process sub-agents reuse the parent's `McpManager` and its warm MCP connections. The tool filtering happens at the `tool_map` level — the sub-agent only sees the tools in its allowlist, but the underlying MCP connections are shared.

```
Parent Agent
  ├── McpManager (owns connections to filesystem, web, github, ...)
  ├── tool_map: {filesystem__read_file, filesystem__bash, web__web_fetch, ...}
  │
  └── Sub-Agent (explore type)
        ├── McpManager: same instance (shared)
        └── tool_map: {filesystem__read_file, web__web_fetch, web__web_search}
                      (filtered subset — no write/mutating tools)
```

---

## 6. Implementation Roadmap

### Phase 1 — Core sub-agent ✅ Completed (2026-03-09)

1. **`SubAgentRunner`** (`sub_agent.py`) — creates and runs a lightweight in-process TurnEngine for a single task
   - Accepts: task prompt, agent type, parent tools (filtered by type)
   - Returns: `SubAgentResult` with text summary, usage metrics, turn count, timeout flag
   - Enforces: timeout (`asyncio.wait_for`), tool restriction (read-only filtering for explore)
   - Uses `BufferedChannel` (no terminal IO), `BaseTurnEvents` subclass for message collection
   - Fresh provider instance per sub-agent (no prompt caching — short-lived)
2. **`spawn_subagent` pseudo-tool** — handled inline in TurnEngine alongside `ask_user` and `tool_search`
   - Multiple concurrent sub-agent calls execute via `asyncio.gather`
   - Sub-agent usage metrics aggregate to parent via `on_api_call_completed(usage, "subagent:{type}")`
   - Channel events emitted for tool_started/completed with `"subagent:{type}"` name
3. **Agent type configs** — `SubAgentType` enum with `SubAgentTypeConfig` per type:
   - `explore`: read-only tools (filtered via `_is_read_only_tool`), lower temperature (0.3)
   - `summarize`: no tools, single turn
   - `general`: all parent tools, parent model
4. **System prompt directive** (`_SUBAGENT_DIRECTIVE`) — tells the LLM when and how to delegate
5. **Config** — `SubAgentsEnabled` (default false), `SubAgentModel`, `SubAgentTimeout`, `SubAgentMaxTurns`, `SubAgentMaxTokens`
6. **Tests** — 27 tests covering tool filtering, schema, runner execution, model selection, TurnEngine integration

### Phase 2a — Routing policy and enable by default ✅ Completed (2026-03-12)

5. **Enhanced routing directive** — `_SUBAGENT_DIRECTIVE` in `system_prompt.py` rewritten with:
   - Explicit cost motivation (sub-agent explore ~$0.01 vs polluting main context)
   - Clear DELEGATE/DO NOT delegate rules with specific task categories
   - Concrete examples of good and bad delegation
   - Guidance for parallel sub-agent spawning
6. **Enabled by default** — `SubAgentsEnabled: true` in `config-base.json`
7. **Tests** — 6 new tests: config parsing (3), directive content validation (3)

### Phase 2b — Observability and persistence ✅ Completed (2026-03-12)

8. **Metrics aggregation** — sub-agent usage aggregated to parent `SessionAccumulator` via `on_api_call_completed`; model subtotals track Haiku separately from Sonnet
9. **Channel integration** — `emit_tool_started` / `emit_tool_completed` already emitted with `subagent:{type}` name in Phase 1
10. **Memory tracking** — `on_subagent_completed` callback added to `TurnEvents` protocol; `Agent` implements it by emitting `subagent.completed` to the events table with agent_type, task (500 char cap), result_summary (500 char cap), turns, timed_out, cost_usd, api_calls
11. **Tests** — 1 new test (`test_on_subagent_completed_called`) verifying all payload fields; `_ListEvents` extended to capture calls
12. **Manual test** — Section 12 added to [MANUAL-TEST-sub-agents.md](../../docs/testing/MANUAL-TEST-sub-agents.md) covering events table queries, truncation, timeout flag, concurrent events, model breakdown, per-call log, budget tracking

### Phase 3 — Async sub-agents via broker (3-5 days)

The async pattern doesn't need new infrastructure — it bridges the agent's tool dispatch to the existing broker job system.

10. **`spawn_background_task` pseudo-tool** — creates a broker run (`--run "prompt"`) from within a conversation. The main agent's turn continues (or ends) without waiting.
11. **Result delivery via channel adapters** — when the background task completes, results are delivered through configured channels (WhatsApp, Discord, webhooks, API server WebSocket). Reuses the broker's existing `response_router` → `channels` pipeline.
12. **Parallel blocking sub-agents** — multiple `spawn_subagent` calls in the same turn execute concurrently (already works via `asyncio.gather` in TurnEngine).
13. **Configurable nesting depth** (1-3) with depth tracking.

```
Blocking (Phase 1):                    Async (Phase 3):
  Parent turn                            Parent turn
    ├── spawn_subagent("search X")         ├── spawn_background_task("research Y")
    ├── [waits]                            ├── broker creates --run job
    ├── gets result as tool_result         ├── parent continues / ends turn
    └── continues reasoning                │
                                           ... later ...
                                           │
                                           └── broker job completes
                                               → channel adapter delivers result
                                               → WhatsApp / Discord / webhook / WS
```

### Phase 4 — Advanced (future)

14. **Mode selector integration** — route batch/analysis tasks to specialized sub-agent types automatically
15. **Custom agent types** — user-defined types in config (name, model, tool allowlist, system prompt)
16. **Sub-agent resume** — store sub-agent state, allow continuation if interrupted
17. **Background task status** — `/tasks` slash command to list active background tasks and their status

---

## 7. Key Files to Modify

| File | Changes |
|------|---------|
| `turn_engine.py` | Handle `spawn_subagent` pseudo-tool (like `ask_user`, `tool_search`) |
| `agent.py` | No changes in Phase 1 — sub-agent is internal to TurnEngine |
| `system_prompt.py` | Add `_SUBAGENT_DIRECTIVE` with usage guidance |
| `agent_config.py` | Add `SubAgentsEnabled`, `SubAgentModel`, `SubAgentTimeout` fields |
| `app_config.py` | Parse new config fields |
| `tool.py` | No changes — ToolResult already sufficient |
| New: `sub_agent.py` | `SubAgentRunner`, agent type definitions, tool allowlists |

---

## 8. Open Questions

1. **Should the LLM decide when to use sub-agents, or should we force it?** Claude Code lets the LLM decide (it has the Task tool). We could also auto-delegate based on heuristics (e.g., if the LLM calls web_search 3+ times in a row, suggest a sub-agent next time).

2. **How much of the parent's system prompt should sub-agents inherit?** Claude Code gives sub-agents a fresh, role-specific prompt. OpenClaw injects AGENTS.md + TOOLS.md. Full inheritance wastes tokens; too little and the sub-agent lacks context about the user's working environment.

3. **Should sub-agents see the parent's conversation summary?** A brief context injection ("The user is working on X. Your task is Y.") might improve relevance without bloating the sub-agent's context.

4. **MCP connection sharing thread safety** — the MCP Python SDK uses asyncio, which is single-threaded. Concurrent tool calls from parent and sub-agent should be safe (asyncio.gather), but needs verification under load.

5. **Sub-agent tool result formatting** — should the sub-agent's response go through the parent's ToolFormatting pipeline, or bypass it? The summary is already concise text, so formatting adds no value.

---

## 9. Success Criteria

- A multi-file search task that currently consumes ~30K tokens in the main context should consume <500 tokens (the sub-agent's summary)
- Sub-agent explore tasks should complete in <10 seconds with Haiku
- No regression in main agent quality — the LLM should use sub-agents naturally when appropriate
- Sub-agent failures (timeout, error) should be reported cleanly as tool errors, not crash the parent
- Total cost of a sub-agent explore task should be <$0.01 (Haiku pricing)

---

## 10. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM doesn't use sub-agents effectively | Medium — feature goes unused | Strong system prompt directive with examples; consider auto-delegation heuristics |
| Sub-agent loops or burns tokens | Medium — cost spike | Turn limit (10-20), timeout (60-120s), token budget |
| MCP connection contention | Low — asyncio is single-threaded | Verify with concurrent parent + sub-agent tool calls |
| Sub-agent quality too low with Haiku | Medium — bad summaries | Evaluate Haiku on real tasks; fall back to Sonnet for general type |
| In-process sub-agent crashes parent | Low — Python exceptions are catchable | Wrap sub-agent execution in try/except; return error as ToolResult |
| Context isolation leaks (shared mutable state) | Medium — subtle bugs | Sub-agent gets fresh message list, own turn counter; no shared mutable state except MCP connections |
