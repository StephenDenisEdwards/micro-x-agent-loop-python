# Sub-Agent Architecture Comparison: Claude Code vs. OpenClaw vs. OpenAI Agents SDK vs. LangGraph

**Date:** 2026-02-26
**Status:** Complete
**Subject:** Four-way comparison of how Claude Code, OpenClaw, the OpenAI Agents SDK, and LangGraph design, spawn, isolate, and manage sub-agents -- with analysis of trade-offs and lessons for micro-x

---

## 1. Executive Summary

All four systems support delegating work to sub-agents, but from fundamentally different design philosophies:

- **Claude Code** treats sub-agents as **short-lived, disposable specialists** -- lightweight, role-typed, context-isolated, one level deep. The parent orchestrates; sub-agents execute and return a summary.
- **OpenClaw** treats sub-agents as **autonomous background workers** -- asynchronous, potentially nested, with their own session lifecycle, concurrency controls, and channel-based result delivery. Sub-agents are closer to independent processes than function calls.
- **OpenAI Agents SDK** offers **two distinct patterns**: **handoffs** (peer-to-peer delegation where the target takes over the conversation) and **agents-as-tools** (manager/orchestrator pattern where the parent retains control). Both are implemented as tool calls, but with opposite control-flow semantics.
- **LangGraph** treats sub-agents as **nodes in a stateful graph** -- subgraphs with typed state schemas, connected via explicit edges or dynamic `Command` routing. Agents are composed structurally at graph-build time, with control flow defined by graph topology, not runtime tool calls.

---

## 2. Spawn Mechanism

### Claude Code

The parent agent calls the built-in **`Task`** tool with a `subagent_type`, `prompt`, and optional `model` override. The SDK spawns a new agent instance (either foreground-blocking or background) and returns a summary when complete.

```
Parent -> Task(subagent_type="Explore", prompt="Find all API endpoints") -> Summary <- Sub-agent
```

Key properties:
- **Synchronous by default** -- parent blocks until sub-agent finishes (foreground mode)
- **Optional background mode** -- parent continues working; notified on completion
- **Resumable** -- sub-agent returns an `agentId` that can be passed to `resume` for follow-up work
- The Task tool is a regular tool call within the agent loop -- no special protocol

### OpenClaw

The parent calls **`sessions_spawn`** with a task description, model override, and optional thinking config. The call returns **immediately** with `{ status: "accepted", runId, childSessionKey }`. The sub-agent runs asynchronously in its own session.

```
Parent -> sessions_spawn(task) -> { runId, childSessionKey } (immediate)
                                     |
                              Sub-agent runs in background
                                     |
                              Announce step posts summary to requester channel
```

Key properties:
- **Always asynchronous** -- parent never blocks on sub-agent completion
- **Channel-based result delivery** -- results posted back as messages, not tool return values
- **Session-scoped** -- each sub-agent gets its own session key (`agent:<agentId>:subagent:<uuid>`)
- Sub-agent management via dedicated tools: `/subagents`, `/subagents kill <id>`

### OpenAI Agents SDK

Two distinct spawn mechanisms coexist:

**Handoffs** -- the parent agent relinquishes control to the target agent. The target takes over the conversation entirely.

```
Parent -> LLM calls transfer_to_refund_agent -> Refund Agent takes over -> Final output
```

**Agents-as-tools** -- the parent invokes a sub-agent as a tool call via `agent.as_tool()`. The parent retains control and receives the sub-agent's result as a tool return value.

```
Manager -> LLM calls specialist_tool -> Specialist runs (separate Runner.run()) -> Result returns to Manager
```

Key properties:
- **Handoffs are synchronous within a single `Runner.run()`** -- no separate process, the active agent simply switches
- **Agents-as-tools create a nested `Runner.run()`** -- isolated execution with independent `max_turns`
- **Both are LLM-driven** -- the model chooses when to hand off or call an agent-tool
- **`on_handoff` callback** allows side effects (logging, data fetching) at delegation time
- **`is_enabled`** allows runtime toggling of handoffs/tools (disabled = hidden from LLM)

### LangGraph

Sub-agents are **subgraphs composed into a parent graph** at build time. Two composition patterns exist:

**Direct node addition (shared state keys)** -- pass a compiled subgraph as a node:

```python
parent_builder.add_node("research_agent", research_subgraph)  # CompiledGraph as node
```

**Wrapper function (different schemas)** -- transform state at boundaries:

```python
def call_research(state: ParentState):
    result = research_subgraph.invoke({"query": state["user_input"]})
    return {"findings": result["answer"]}

parent_builder.add_node("research", call_research)
```

**Handoff-style delegation** via `create_handoff_tool` or manual `Command` objects:

```
Agent A -> Command(goto="agent_b", update={...}, graph=Command.PARENT) -> Agent B takes over
```

Key properties:
- **Structural composition** -- agents wired together at graph-build time, not spawned at runtime
- **`Command` object** combines state update + routing in a single return value
- **`Command.PARENT`** enables cross-graph navigation (subgraph node routes to parent graph)
- **`create_handoff_tool`** (langgraph-supervisor) creates handoff tools similar to OpenAI's pattern
- **Supervisor pattern** wraps sub-agents as tools the supervisor can invoke
- **Swarm pattern** uses peer-to-peer handoff tools (no central supervisor)

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Spawn API | `Task` tool (built-in) | `sessions_spawn` tool | Handoff (implicit tool) or `as_tool()` | Subgraph as node (build-time) or `Command`/handoff tool (runtime) |
| Return type | Summary (tool result) | Acceptance receipt (runId) | Handoff: takes over; as_tool: tool result | State update via reducers |
| Default blocking | Foreground (blocking) | Non-blocking (always async) | Synchronous (within same `Runner.run()`) | Synchronous (within same `graph.invoke()`) |
| Background option | Yes (`run_in_background`) | N/A -- always background | No (code-level `asyncio.gather` for parallelism) | No (`Send()` for parallel fan-out within graph) |
| Resume support | `agentId` + `resume` parameter | Session key for re-entry | Session object for multi-turn persistence | Checkpoint + `thread_id` for full state resume |
| Who decides to delegate | Parent LLM or auto-match | Parent LLM | LLM chooses handoff/tool call | Graph topology (structural) or LLM via handoff tools |
| Composition time | Runtime (dynamic) | Runtime (dynamic) | Runtime (dynamic, LLM-driven) | Build-time (structural) + runtime (Command routing) |

---

## 3. Nesting Depth

### Claude Code: Strictly flat (depth 1)

Sub-agents **cannot spawn their own sub-agents**. The `Task` tool is excluded from sub-agent tool sets. If multi-step orchestration is needed, the parent chains sequential sub-agent calls.

```
Parent --+-- Sub-agent A (returns)
         +-- Sub-agent B (returns)    <- sequential, parent orchestrates
         +-- Sub-agent C (returns)
```

**Rationale:** Simplicity. Prevents runaway agent chains, makes cost/token usage predictable, and avoids complex result-propagation logic.

### OpenClaw: Configurable nesting (depth 1-5, default 1)

`maxSpawnDepth` controls how many levels of delegation are allowed. At depth 1 (default), sub-agents are leaf workers. At depth 2+, intermediate sub-agents become **orchestrators** that can spawn their own children.

```
Parent (depth 0)
+-- Orchestrator (depth 1, maxSpawnDepth >= 2)
|   +-- Worker A (depth 2, leaf)
|   +-- Worker B (depth 2, leaf)
+-- Worker C (depth 1, leaf)
```

Results flow back up the chain: depth-2 announces to depth-1, depth-1 announces to parent.

**Rationale:** Flexibility. Complex tasks (e.g. "research 5 companies and summarize") benefit from an orchestrator that fans out work to leaf agents, then synthesizes results.

### OpenAI Agents SDK: Unlimited (bounded by `max_turns`)

There is **no explicit depth limit** on handoff chains or agent-as-tool nesting. Handoff targets can themselves have handoffs, and agents invoked via `as_tool()` can have their own handoffs and tool-agents.

```
Handoffs:  Agent A -> Agent B -> Agent C -> Agent A (circular possible!)
As-tools:  Manager -> Specialist (own Runner.run) -> Sub-specialist (own Runner.run)
```

**Circular handoffs are allowed** -- A can hand off to B which hands off back to A. The only termination mechanism is `max_turns` (default 10), which counts globally across all agents within a single `Runner.run()`.

For agents-as-tools, each `as_tool()` call creates a **separate `Runner.run()`** with its own independent `max_turns`, so nesting depth is bounded per level but unlimited in total depth.

**Rationale:** Maximum flexibility, trusting the developer to set appropriate `max_turns`. The SDK avoids imposing structural constraints.

### LangGraph: Unlimited (structural nesting via subgraphs)

LangGraph supports **arbitrary nesting depth** -- subgraphs can contain subgraphs, which can contain further subgraphs. Each level transforms state at boundaries.

```
Parent graph
+-- Child subgraph (CompiledGraph as node)
|   +-- Grandchild subgraph (compiled, nested)
|   +-- Grandchild subgraph B
+-- Child subgraph B
```

**No explicit depth limit.** Unlike OpenClaw's `maxSpawnDepth` or OpenAI's `max_turns`, LangGraph has no built-in mechanism to cap nesting depth. Termination is structural -- graphs run until reaching `END` nodes.

**Circular routing is possible** via `Command` -- agent A can route to agent B which routes back to A. Swarm patterns explicitly support this (`active_agent` tracks who's currently in control).

**Hierarchical teams** -- supervisors can manage other supervisors, creating nested hierarchies where each team is a subgraph with its own supervisor.

**Rationale:** Graph topology defines execution flow. Developers control depth through graph structure, not runtime counters. Finite graphs naturally terminate; cyclic graphs use conditional edges or `remaining_steps` tracking.

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Max nesting | 1 (hard limit) | 5 (configurable, default 1) | Unlimited (bounded by `max_turns`) | Unlimited (structural, via nested subgraphs) |
| Circular delegation | Impossible | Not applicable (async fire-and-forget) | Possible (A->B->A), bounded by `max_turns` | Possible (via `Command` routing), bounded by conditional edges or step tracking |
| Orchestrator pattern | Parent only | Any depth-N agent if `maxSpawnDepth > N` | Handoff chains or nested `as_tool()` runs | Supervisor subgraph, hierarchical teams, or swarm |
| Result propagation | Direct (tool result) | Chain of announce steps | Handoff: last agent outputs; as_tool: tool result | State updates via reducers (shared keys) or explicit transformation (different schemas) |
| Runaway risk | None | Mitigated by depth cap + concurrency limits | Mitigated by `max_turns` (raises `MaxTurnsExceeded`) | Mitigated by `remaining_steps` tracking or conditional edges |
| Depth control mechanism | Tool exclusion (Task denied) | `maxSpawnDepth` config parameter | `max_turns` counter | Graph structure + conditional edges |

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

### OpenAI Agents SDK

Context handling differs radically between the two patterns:

**Handoffs -- full history transfer (default):**
- Target agent receives the **entire conversation history** by default (all messages, tool calls, tool results, the handoff call itself)
- `RunContextWrapper` (local state, never sent to LLM) is **shared** -- the same instance continues across handoffs
- History can be filtered per-handoff via `input_filter` or globally via `RunConfig.handoff_input_filter`
- Built-in filters: `remove_all_tools` (strips tool messages), `nest_handoff_history` (collapses prior transcript into a summary)
- Priority: per-handoff filter > per-handoff nesting > RunConfig filter > RunConfig nesting > raw history

**Agents-as-tools -- isolated by default:**
- Sub-agent receives **only the tool input string** (or structured `parameters` if specified)
- No parent conversation history is passed
- Sub-agent runs in a separate `Runner.run()` with its own context
- Results return as tool output to the parent

### LangGraph

Context handling depends on the composition pattern:

**Shared state keys (direct node addition):**
- Subgraph reads from and writes to the parent's state channels **automatically** for overlapping keys
- Subgraph-only keys remain internal and **never leak to parent**
- Full message history is shared if both use `MessagesState` with `add_messages` reducer

**Different schemas (wrapper function):**
- **Complete isolation** -- the node function explicitly maps fields between parent and child schemas
- No automatic state sharing; child keys inaccessible at parent level
- Equivalent to Claude Code's isolation but with structured state instead of free-form prompts

**Handoff patterns (`create_handoff_tool`):**
- Default passes the **entire conversation history** to the receiving agent (similar to OpenAI handoffs)
- Custom handoff tools can summarize or truncate context for performance
- `Command.PARENT` allows subgraph nodes to update parent state directly

**Cross-agent shared state:**
- `Store` provides namespaced long-term memory accessible by any agent in the graph
- Per-agent or shared namespaces for fine-grained control
- `ToolRuntime` gives tools access to full graph state for context injection

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Parent history inherited | No | No | Handoff: yes (default, filterable); as_tool: no | Shared keys: yes (automatic); different schemas: no; handoff: yes (default) |
| System prompt | Agent-type-specific (Explore, Plan, etc.) | Reduced bootstrap (AGENTS.md + TOOLS.md only) | Per-agent `instructions` field | Per-agent `system_prompt` or `prompt` parameter |
| Shared local state | No | No | Handoff: yes (`RunContextWrapper` shared); as_tool: no | Via graph state (shared keys) or `Store` (namespaced) |
| History filtering | N/A (no history passed) | N/A | `input_filter`, `nest_handoff_history`, `remove_all_tools` | Custom handoff tools, `pre_model_hook` for trimming |
| Result format | Free-form summary (tool result) | Normalized template (status, result, notes, stats) | Handoff: final agent's output; as_tool: `RunResult` | Typed state updates via reducers |
| Full transcript access | Parent never sees it | Stored in JSONL, accessible via `/subagents` | Within same `Runner.run()` (handoff) or isolated (as_tool) | Stored in checkpoints, accessible via `get_state(subgraphs=True)` |
| State leak prevention | Task tool isolation | Session-scoped JSONL | RunContext not sent to LLM | Subgraph-only keys never surface to parent |

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

### OpenAI Agents SDK

Each agent has its own `model` field:

```python
Agent(name="Triage", model="gpt-4o")
Agent(name="Quick Check", model="gpt-4o-mini")
```

There is no concept of agent "types" with default models. Model selection is entirely per-agent definition. The `model_settings` field provides fine-grained control (temperature, `parallel_tool_calls`, etc.).

Both handoff targets and agents-as-tools use whatever model is defined on the target `Agent` object. There is no inheritance from the calling agent.

### LangGraph

Each agent can use a different model, specified at agent creation:

```python
from langchain.chat_models import init_chat_model

research_agent = create_react_agent(
    model=init_chat_model("claude-haiku-4-5-20251001"),
    tools=[web_search],
    name="research"
)
supervisor = create_react_agent(
    model=init_chat_model("gpt-4o"),
    tools=[do_research],
    name="supervisor"
)
```

Key properties:
- **Per-agent definition** -- model set on `create_react_agent` or `create_agent` call
- **No inheritance** -- each agent explicitly declares its model
- **Model-agnostic** -- supports any LangChain-compatible model (OpenAI, Anthropic, Google, etc.)
- **Dynamic binding** -- models can be swapped at runtime via callable model parameters
- **No built-in model tiers** -- model selection is entirely the developer's responsibility

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Default model | Per agent type (Haiku for read-only, inherit for others) | Inherited from caller | Per-agent definition (no inheritance) | Per-agent definition (no inheritance) |
| Override mechanism | `model` param on Task call | `sessions_spawn.model` or config default | `Agent(model=...)` on definition | `init_chat_model(...)` on agent creation |
| Built-in model tiers | Yes (Haiku/Sonnet/Opus per type) | No (uniform, config-driven) | No (per-agent, any OpenAI model) | No (per-agent, any LangChain model) |
| Thinking budget | Not configurable per sub-agent | `sessions_spawn.thinking` override | `model_settings` per agent | Model-specific parameters via `init_chat_model` kwargs |
| Cost optimization pattern | Automatic (role-typed defaults) | Manual (config) | Manual (per-agent model choice) | Manual (per-agent model choice) |
| Provider lock-in | Anthropic only | Anthropic primary (config-driven) | OpenAI primary (provider-agnostic via SDK) | None (any LangChain model) |

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

### OpenAI Agents SDK

Tools are **scoped per agent definition**. Each agent has its own `tools` list. When a handoff occurs, the target agent's tools **completely replace** the previous agent's tools.

```python
billing_agent = Agent(name="Billing", tools=[get_invoice, process_refund])
tech_agent = Agent(name="Technical", tools=[search_docs, run_diagnostic])
triage = Agent(name="Triage", tools=[get_user_info], handoffs=[billing_agent, tech_agent])
# After handoff to billing: get_user_info removed, get_invoice + process_refund added
```

Key properties:
- **No implicit tool sharing** -- shared tools must be explicitly added to each agent
- **MCP servers are also scoped per agent** -- different agents can connect to different MCP endpoints
- **Runtime toggling** -- `@function_tool(is_enabled=lambda ctx, agent: ...)` hides tools from the LLM dynamically
- **MCP tool filtering** -- `create_static_tool_filter(allowed_tool_names=[...])` or dynamic context-aware filters
- No concept of "agent types" restricting tools -- all tool scoping is per-agent definition

### LangGraph

Tools are **scoped per agent** and enforced by per-agent `ToolNode` instances:

```python
# Each agent has its own tools
research_agent = create_react_agent(model, tools=[web_search, arxiv_search])
calendar_agent = create_react_agent(model, tools=[create_event, list_events])

# Supervisor sees agent-tools (high-level), not individual API tools
supervisor = create_react_agent(model, tools=[do_research, manage_calendar])
```

Key properties:
- **ToolNode isolation** -- each agent's ToolNode has its own tool registry; models cannot call arbitrary tools
- **Handoff tools as access control** -- `create_handoff_tool` defines which agents can route to which others, creating an implicit access control graph
- **Dynamic tool binding** -- tools can be resolved at runtime based on state (e.g., middleware swaps tools based on `current_step`)
- **State injection** -- tools can receive graph state via `InjectedState` and `InjectedStore`
- **No deny lists** -- tools scoped by inclusion (like OpenAI), not exclusion (like OpenClaw)
- **MCP support** -- per-agent MCP server configuration

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Policy model | Per agent type (hardcoded + custom allowlists) | Per depth level + per-agent overrides | Per agent definition (explicit `tools` list) | Per agent definition (explicit `tools` list) |
| Tool replacement on delegation | N/A (isolated context) | N/A (isolated session) | Full replacement (handoff); isolated (as_tool) | Per-agent ToolNode; handoff changes active agent's tools |
| Deny granularity | Specific tool names | Tool categories + session tools by depth | No deny lists; exclusion by omission | No deny lists; exclusion by omission |
| Spawn prevention | Task tool excluded from sub-agents | Session tools excluded by depth | No structural prevention (unlimited nesting) | No structural prevention (graph topology controls) |
| Sandbox layer | Git worktree isolation (optional) | Docker container isolation (configurable) | None built-in | None built-in |
| Runtime toggling | N/A | N/A | `is_enabled` on tools and handoffs | Dynamic tool binding via callable models / middleware |
| MCP scoping | Per agent (SDK) | Per agent (config) | Per agent (`mcp_servers` field) | Per agent (config) |
| State-aware tools | No | No | No | Yes (`InjectedState`, `InjectedStore` for graph-state access) |

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

### OpenAI Agents SDK

Two parallelism patterns:

**Code-level (`asyncio.gather`):**
```python
results = await asyncio.gather(
    Runner.run(agent_a, text),
    Runner.run(agent_b, text),
    Runner.run(agent_c, text),
)
```
Deterministic, lowest latency, full developer control. No SDK-level concurrency caps.

**LLM-driven (`parallel_tool_calls`):**
```python
Agent(model_settings=ModelSettings(parallel_tool_calls=True), tools=[a.as_tool(...), b.as_tool(...)])
```
The LLM decides which tools to call in parallel. Higher latency (planning overhead), but adaptive.

Limits:
- `max_turns` (default 10) -- global across all agents within a single `Runner.run()` (handoff pattern)
- Per-agent `max_turns` on `as_tool()` -- independent limit for nested runs
- `MaxTurnsExceeded` exception raised when exceeded
- No built-in concurrency caps, queue isolation, or auto-cleanup

### LangGraph

Concurrency is built into the graph execution model via **super-steps**:

**Automatic parallelism (static edges):**
```python
# node_a fans out to node_b and node_c (parallel execution within same super-step)
builder.add_edge("node_a", "node_b")
builder.add_edge("node_a", "node_c")
```

**Dynamic fan-out (`Send()` API):**
```python
def continue_to_agents(state):
    return [Send("research_agent", {"topic": t}) for t in state["topics"]]

builder.add_conditional_edges("planner", continue_to_agents)
```
Number of parallel tasks determined at runtime. Each `Send()` receives its own custom state. Results merge via reducers.

**Concurrency control:**
```python
result = graph.invoke(inputs, config={"max_concurrency": 3})
```

Key properties:
- **Super-step parallelism** -- all active nodes execute concurrently within a super-step, then results merge atomically
- **Atomic super-step failure** -- if one parallel node fails, the **entire super-step fails** (neither result saved)
- **`Send()` for map-reduce** -- dynamic fan-out with variable parallelism and reducer-based collection
- **Defer pattern** -- synchronization barriers for asymmetric completion times
- **Stateful subagent limitation** -- parallel calls to the same stateful subagent cause checkpoint namespace conflicts (must use sequential calls or unique namespaces)

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Concurrent sub-agents | Unlimited (practical) | `maxConcurrent` (8) + `maxChildrenPerAgent` (5) | Unlimited (`asyncio.gather` or `parallel_tool_calls`) | Unlimited (super-step parallelism, `Send()` fan-out); `max_concurrency` config optional |
| Turn limits | `max_turns` per sub-agent | `timeoutSeconds` per agent | `max_turns` global (handoff) or per-agent (as_tool) | `remaining_steps` tracking or conditional edges |
| Queue isolation | None (in-process) | Dedicated `subagent` queue lane | None (in-process) | None (in-process, super-step batching) |
| Cascade stop | N/A (foreground blocks, background notifies) | `/stop` cascades to all children | N/A (synchronous within `Runner.run()`) | Graph terminates at `END` node; `interrupt()` for manual pause |
| Auto-cleanup | Worktree auto-cleanup (if no changes) | Session archived after 60 minutes | None | Checkpoints persist until explicitly deleted |
| Parallelism model | Multiple Task calls in one response | Async fire-and-forget | `asyncio.gather` or LLM-driven parallel tool calls | Super-step edges, `Send()` API, or agents-as-tools with parallel invocation |
| Failure semantics | Per-agent (independent) | Per-agent (independent) | Per-agent (independent) | Atomic super-step (all-or-nothing within a step) |

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

### OpenAI Agents SDK

Security is **guardrail-based** using a tripwire pattern:

**Input guardrails** -- run on the **first agent only** (not on handoff targets):
```python
Agent(name="Triage", input_guardrails=[content_filter])
```

**Output guardrails** -- run on the **last agent only** (the one producing final output):
```python
Agent(name="Refund", output_guardrails=[pii_check])
```

**Global guardrails** -- via `RunConfig` to enforce across all agent boundaries:
```python
RunConfig(input_guardrails=[global_guard], output_guardrails=[global_guard])
```

**Tool guardrails** -- scoped to specific `@function_tool` declarations, fire regardless of which agent calls the tool.

**`needs_approval`** on `as_tool()` -- adds human-in-the-loop gating before a sub-agent runs.

**MCP approval policies** -- per-server or per-tool (`"always"`, `"never"`, or callback-based).

Key difference: guardrails in OpenAI are **halt-on-trip** (raise `InputGuardrailTripwireTriggered` / `OutputGuardrailTripwireTriggered`), not allow/deny/modify like Claude Code's hooks.

### LangGraph

Security relies on **structural mechanisms** rather than dedicated guardrail primitives:

**`interrupt()` for human-in-the-loop:**
```python
def approval_node(state):
    decision = interrupt({"question": "Approve?", "details": state["action"]})
    return Command(goto="proceed" if decision else "cancel")
```
Pauses execution at any point, saves state via checkpointer, waits indefinitely for user response.

**`HumanInTheLoopMiddleware`** -- declarative interrupt-on-tool patterns:
```python
calendar_agent = create_agent(
    model,
    tools=[create_event],
    middleware=[HumanInTheLoopMiddleware(interrupt_on={"create_event": True})]
)
```

**Tool-level gating** -- tools can internally call `interrupt()` to request approval before executing.

**No built-in guardrails** -- no equivalent of OpenAI's input/output tripwires or Claude Code's deny/allow modes. Developers implement validation in `pre_model_hook`, `post_model_hook`, or custom nodes.

**No OS-level sandboxing** -- no Docker containers or filesystem isolation.

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Permission model | Mode-based (5 modes) + hooks | Multi-layer pipeline (tools + sandbox + approvals) | Guardrail tripwires + `needs_approval` | `interrupt()` + middleware + custom nodes |
| OS-level isolation | None (process-level only) | Docker containers with network/filesystem isolation | None built-in | None built-in |
| Approval flow | User prompts via CLI | Chat-forwarded approvals across channels | `needs_approval` on `as_tool()`, MCP approval callbacks | `interrupt()` pauses graph, resumes on user response |
| Read-only enforcement | Agent type (Explore, Plan) | Sandbox `workspaceAccess: "ro"` + tool deny lists | No built-in read-only mode | No built-in (tool scoping by omission) |
| Guardrail hooks | PreToolUse/PostToolUse (fire for sub-agents) | before_tool_call/after_tool_call per plugin | Input/output/tool guardrails (tripwire pattern) | `pre_model_hook`/`post_model_hook` on `create_react_agent` |
| Guardrail scope across agents | Fire for all agents | Fire for all agents | Input: first agent only; Output: last agent only (unless `RunConfig`) | Per-agent (each agent has own hooks/middleware) |
| Guardrail execution | Synchronous (hook chain) | Synchronous (plugin chain) | Parallel with LLM call (default) or blocking | Synchronous (node execution) |
| HITL in subgraphs | N/A (depth 1 only) | N/A (async, no built-in HITL) | N/A (no built-in HITL) | Full support -- `interrupt()` in subgraphs bubbles up, checkpointed at all levels |

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

### OpenAI Agents SDK

Result delivery depends on the pattern:

**Handoffs:**
- The **last agent** in the handoff chain produces the final output
- `RunResult.final_output` contains the typed output (if `output_type` set) or raw text
- `RunResult.last_agent` identifies which agent produced the result
- Streaming emits `agent_updated_stream_event` when the active agent changes mid-stream

**Agents-as-tools:**
- Sub-agent's `RunResult` is converted to a tool result string and returned to the parent
- `custom_output_extractor` allows transforming the result before returning
- `on_stream` callback provides streaming events from the nested agent

**Structured output:**
- Any agent can define `output_type` (Pydantic model) for typed, validated results
- Enforced via constrained decoding -- the LLM must produce valid JSON matching the schema

### LangGraph

Results are **typed state updates** flowing through the graph:

**Via reducers (shared state keys):**
- Sub-agent writes to state channels using reducers (e.g., `add_messages` appends, `add` concatenates lists)
- Parent receives overlapping keys automatically after subgraph completes
- Multiple parallel agents merge safely via reducer functions

**Via explicit transformation (different schemas):**
- Wrapper function maps subgraph output to parent state fields
- Gives full control over what surfaces to the parent

**Structured output:**
- `create_react_agent(response_format=PydanticModel)` enforces structured output via constrained decoding
- Output schema validated before reaching the `END` node

**Streaming during delegation:**
- 5 stream modes (values, updates, messages, custom, debug)
- `subgraphs=True` enables streaming from nested agents with namespace tuples identifying the source
- `get_stream_writer()` for custom data emission from within agent nodes

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Delivery mode | Synchronous tool result | Asynchronous channel message | Synchronous (handoff: final output; as_tool: tool result) | Synchronous state update (via reducers or transformation) |
| Format | Free-form summary | Normalized template (status, result, notes, stats) | Free-form or typed (`output_type` Pydantic model) | Typed state updates; optional `response_format` for structured output |
| Structured output | No | No | Yes (JSON schema constrained decoding) | Yes (`response_format` on `create_react_agent`) |
| Cost tracking | Available in ResultMessage (parent level) | Per-sub-agent in announce stats | Via `RunResult` usage fields | Via LangSmith tracing or custom metrics in state |
| Suppress option | N/A | `ANNOUNCE_SKIP` | N/A | Subgraph-only keys never surface to parent |
| Streaming during delegation | Background notification on completion | N/A (async) | `agent_updated_stream_event` (handoff); `on_stream` (as_tool) | 5 stream modes with `subgraphs=True` namespace filtering |
| Output transformation | N/A | N/A | `custom_output_extractor` on `as_tool()` | Wrapper function (different schemas) or `pre_model_hook` |
| Merge semantics | N/A (single result) | N/A (single announcement) | N/A (single result) | Reducer-based merge for parallel agent outputs |

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

### OpenAI Agents SDK

Agents are Python objects:

```python
refund_agent = Agent(
    name="Refund Agent",
    instructions="Handle refund requests.",
    handoff_description="Transfer for refund-related questions",
    tools=[process_refund, get_order],
    model="gpt-4o-mini",
    output_type=RefundResult,
)
```

**Handoff customization** via `handoff()` factory:
```python
escalation = handoff(
    agent=escalation_agent,
    tool_name_override="escalate_to_supervisor",
    on_handoff=log_escalation,
    input_type=EscalationData,
    input_filter=remove_all_tools,
    is_enabled=lambda ctx, agent: ctx.context.user_tier == "premium",
)
```

**Agent-as-tool** via `as_tool()`:
```python
specialist_tool = specialist_agent.as_tool(
    tool_name="ask_specialist",
    tool_description="Consult the domain specialist",
    max_turns=5,
    needs_approval=True,
    parameters=SpecialistInput,
)
```

Auto-delegation: LLM chooses handoffs/tools based on `handoff_description` and tool descriptions. `clone()` method creates agent variants with overrides.

### LangGraph

Agents are defined using **prebuilt factories** or **custom graph construction**:

**Using `create_react_agent` (prebuilt):**
```python
research_agent = create_react_agent(
    model=init_chat_model("claude-haiku-4-5-20251001"),
    tools=[web_search, arxiv_search],
    prompt="You are a research specialist...",
    name="research_agent",
    response_format=ResearchResult,
)
```

**Using `create_supervisor` (langgraph-supervisor):**
```python
workflow = create_supervisor(
    agents=[research_agent, calendar_agent],
    model=model,
    prompt="You coordinate agents...",
    output_mode="full_history",
)
```

**Using `create_swarm` (langgraph-swarm):**
```python
alice = create_agent(model, tools=[tool_a, create_handoff_tool("Bob")], name="Alice")
bob = create_agent(model, tools=[tool_b, create_handoff_tool("Alice")], name="Bob")
workflow = create_swarm([alice, bob], default_active_agent="Alice")
```

**Custom graph (maximum control):**
```python
builder = StateGraph(CustomState)
builder.add_node("agent_a", agent_a_subgraph)
builder.add_node("agent_b", agent_b_subgraph)
builder.add_conditional_edges("router", route_decision)
graph = builder.compile(checkpointer=checkpointer, store=store)
```

Auto-delegation: LLM chooses handoff tools based on tool descriptions (swarm/supervisor), or routing is deterministic via conditional edges.

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Definition format | Markdown frontmatter or SDK dataclass | JSON/JSON5 config | Python `Agent` dataclass | Python factory functions or custom `StateGraph` |
| System prompt | Markdown body or `prompt` field | Workspace files (SOUL.md, AGENTS.md) | `instructions` field (static or dynamic callable) | `prompt` or `system_prompt` (static or Runnable) |
| Auto-delegation | Via `description` matching (LLM-driven) | Via channel bindings (deterministic routing) | Via `handoff_description` / tool description (LLM-driven) | Via handoff tool descriptions (LLM) or conditional edges (deterministic) |
| Agent persistence | Ephemeral (per invocation) | Persistent (own workspace, sessions, memory) | Ephemeral (Python object, reusable across runs) | Ephemeral (graph invocation) with optional stateful subgraphs (`checkpointer=True`) |
| Agent-to-agent | Not supported | Opt-in messaging between named agents | Bidirectional handoffs (A<->B) | Bidirectional via `Command` or handoff tools |
| Agent variants | Custom agent definitions | Per-agent config overrides | `clone()` method for shallow copies | Different `create_react_agent` calls with varied params |
| Structured delegation input | `prompt` string only | Task description string | `input_type` (handoff) or `parameters` (as_tool) | Typed state schemas with explicit field mapping |
| Prebuilt orchestration | None (parent orchestrates manually) | None (config-driven) | None (developer composes) | `create_supervisor`, `create_swarm`, hierarchical teams |

---

## 11. Tracing and Observability

### Claude Code

- Sub-agent transcripts persist independently and survive compaction
- No built-in tracing framework across agent boundaries
- `ResultMessage` provides cost, duration, and usage at the parent level

### OpenClaw

- Per-sub-agent stats in the announce template: runtime, token usage, estimated cost, sessionKey, transcript path
- Full JSONL transcript stored per session, accessible via `/subagents`
- Plugin hooks (`agent_end`) provide post-run inspection

### OpenAI Agents SDK

Built-in tracing spans the full agent chain:

```
Trace: "Customer Support"
+-- AgentSpan: "Triage Agent"
|   +-- GenerationSpan: LLM call
|   +-- HandoffSpan: Triage -> Refund (from_agent, to_agent)
+-- AgentSpan: "Refund Agent"
|   +-- GenerationSpan: LLM call
|   +-- FunctionSpan: "process_refund"
|   +-- GenerationSpan: LLM call (final)
+-- GuardrailSpan: "output_guard"
```

Key span types: `AgentSpan`, `HandoffSpan`, `GenerationSpan`, `FunctionSpan`, `GuardrailSpan`, `MCP_tools_span`, `custom_span`.

`RunConfig` controls trace metadata: `workflow_name`, `trace_id`, `group_id` (links related traces across separate `Runner.run()` calls), `trace_include_sensitive_data`.

Uses `contextvar` for async-safe trace propagation across parallel branches.

### LangGraph

Observability via **LangSmith integration** and **streaming introspection**:

**Streaming with subgraph namespace tuples:**
```python
for chunk in graph.stream(inputs, subgraphs=True, stream_mode="updates"):
    # Output: (namespace_tuple, data)
    # namespace: ("parent_node:<task_id>", "child_node:<task_id>")
    print(chunk)
```

**State inspection at any level:**
```python
subgraph_state = graph.get_state(config, subgraphs=True).tasks[0].state
```

**LangSmith** provides production-grade tracing with hierarchical spans, token usage, latency, and cost tracking across all agents in the graph.

**Graph visualization** -- Mermaid diagrams and LangGraph Studio for visual debugging of multi-agent execution flow.

**Custom data streaming** -- `get_stream_writer()` emits arbitrary data from within agent nodes for real-time progress reporting.

**Debug stream mode** -- maximum information about execution, including full trace data.

### Comparison

| Dimension | Claude Code | OpenClaw | OpenAI Agents SDK | LangGraph |
|---|---|---|---|---|
| Cross-agent tracing | No built-in | Stats in announce template | Full trace spanning all handoffs | LangSmith integration + streaming namespace tuples |
| Span types | N/A | N/A | Agent, Handoff, Generation, Function, Guardrail, MCP, Custom | LangSmith spans (LLM, tool, chain, retriever) |
| Trace linking | N/A | Session key | `group_id` links separate `Runner.run()` calls | `thread_id` links checkpoint history |
| Cost tracking | `ResultMessage` at parent level | Per-sub-agent in announce stats | Per-`RunResult` usage fields | Via LangSmith or custom state tracking |
| Transcript persistence | Separate context (survives compaction) | JSONL per session | In-memory (within `Runner.run()`) | Checkpoints (SQLite/Postgres/Redis) |
| Visual debugging | N/A | N/A | N/A | LangGraph Studio + Mermaid graph visualization |
| Custom metrics | N/A | N/A | `custom_span` context manager | `get_stream_writer()` + custom stream mode |

---

## 12. Architectural Philosophy

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

### OpenAI Agents SDK: Dual-Pattern Model

The SDK offers **two complementary patterns** with opposite control-flow semantics, both implemented as tool calls:

**Handoffs** -- peer-to-peer delegation where the target **takes over** the conversation. Best for routing/escalation workflows where specialization requires a full context switch.

**Agents-as-tools** -- manager/orchestrator pattern where the parent **retains control**. Best for fan-out/fan-in, parallel sub-tasks, and aggregation workflows.

**Strengths:**
- Two patterns cover most multi-agent topologies (routing + orchestration)
- Handoff history filtering gives fine-grained control over context transfer
- Structured input (`input_type`, `parameters`) and output (`output_type`) at delegation boundaries
- Built-in tracing spans the full agent chain with rich span types
- `is_enabled` allows runtime-conditional delegation
- `asyncio.gather` enables true parallel execution
- No artificial depth limits

**Weaknesses:**
- Two patterns = two mental models to learn and choose between
- No built-in concurrency controls (developer must manage `asyncio.gather` limits)
- No OS-level sandboxing
- Circular handoffs can waste tokens if `max_turns` is set too high
- No built-in model-tier optimization (all per-agent definition)
- Guardrail scoping across agents is unintuitive (input: first only; output: last only)

### LangGraph: Graph/Workflow-Engine Model

Sub-agents are **nodes in a typed state graph** with execution flow defined by edges, conditional routing, and the `Command` primitive. The graph is compiled ahead of time; agents are structurally composed rather than dynamically spawned.

**Strengths:**
- Maximum control over execution flow (graph topology is explicit and inspectable)
- Built-in checkpointing enables resume, replay, and fault tolerance across agent boundaries
- `interrupt()` provides first-class human-in-the-loop at any point in the graph
- `Send()` + reducers enable elegant map-reduce and fan-out/fan-in patterns
- `Store` provides namespaced cross-thread memory accessible by any agent
- Rich streaming (5 modes) with subgraph namespace filtering
- Graph visualization (Mermaid, LangGraph Studio) aids debugging
- Provider-agnostic (any LangChain model)
- Prebuilt patterns (`create_supervisor`, `create_swarm`) reduce boilerplate

**Weaknesses:**
- Highest learning curve (state schemas, reducers, Command, super-steps, checkpointers)
- Structural composition is less dynamic than runtime spawning -- graph topology must be defined at build time
- Atomic super-step failure means one bad node can invalidate all parallel results
- No OS-level sandboxing or built-in guardrails
- Stateful subagents conflict with parallel execution (namespace issues)
- Full history handoffs become expensive at scale (no built-in history filtering like OpenAI)
- Heavy dependency tree (LangChain ecosystem)

---

## 13. Key Takeaways for micro-x Design

### 1. Start with Claude Code's simplicity, plan for OpenClaw's flexibility, learn from OpenAI's dual patterns and LangGraph's state management

Claude Code's flat, synchronous model covers 90% of sub-agent use cases. OpenAI's dual-pattern approach (handoffs + agents-as-tools) shows that the remaining 10% splits into two distinct needs: routing (handoffs) and orchestration (agents-as-tools). LangGraph's typed state schemas and reducer-based merging demonstrate how to handle structured data flow between agents. micro-x should start with the function-call model and plan for both routing and orchestration extensions with typed state boundaries.

### 2. Role-typed agents with default models are a powerful pattern

Claude Code is the only framework with automatic model-tier optimization (Haiku for exploration, Opus for reasoning). OpenAI, OpenClaw, and LangGraph all leave model selection entirely to the developer. micro-x should adopt role-typed defaults while allowing overrides.

### 3. Context isolation is non-negotiable, but the degree varies by pattern

All four systems agree: sub-agents should not inherit the parent's full context by default. But OpenAI's handoff pattern and LangGraph's shared-state-keys pattern show that **some** history transfer is valuable for routing workflows. micro-x should default to isolated context (Claude Code style) but offer opt-in history transfer (OpenAI/LangGraph style) for routing use cases.

### 4. Tool restriction must be explicit, not implicit

All four enforce tool access per agent. OpenAI and LangGraph's approach (tools scoped per agent definition, no deny lists) is the simplest. Claude Code's approach (role-typed defaults) is the most opinionated. OpenClaw's approach (depth-based + per-agent overrides) is the most flexible. micro-x should require explicit tool allowlists for sub-agents.

### 5. Structured input and output at delegation boundaries

OpenAI (`input_type`, `output_type`) and LangGraph (typed state schemas with reducers) both support structured I/O at delegation boundaries. This enables reliable programmatic routing based on sub-agent results. micro-x should adopt structured I/O for sub-agent boundaries from the start.

### 6. Handoff history filtering is a valuable pattern

OpenAI's ability to filter, summarize, or strip conversation history during delegation (`remove_all_tools`, `nest_handoff_history`, custom filters) is a powerful context management tool. LangGraph's `pre_model_hook` and custom handoff tools serve a similar purpose. micro-x should implement this for any routing-style delegation.

### 7. Built-in tracing across agent boundaries is essential

OpenAI's tracing (with `HandoffSpan`, `AgentSpan`, and `group_id` linking) and LangGraph's LangSmith integration + streaming namespace tuples provide the best observability stories. Claude Code and OpenClaw provide cost/usage tracking but lack structured cross-agent traces. micro-x should build tracing into the multi-agent architecture from day one.

### 8. Concurrency controls are necessary at scale

Claude Code and OpenAI have no concurrency caps, which works for single-user use. OpenClaw's `maxConcurrent` + `maxChildrenPerAgent` and LangGraph's `max_concurrency` config + atomic super-step failure semantics show different approaches to preventing resource exhaustion. micro-x should include at minimum a global concurrency limit.

### 9. The nesting question: start at 1, cap at 2

Claude Code's depth-1 restriction and OpenClaw's recommended depth-2 both work well. OpenAI's unlimited nesting with `max_turns` as the only guard and LangGraph's unlimited structural nesting are both risky without careful design -- circular handoffs (OpenAI) or unbounded cyclic graphs (LangGraph) can silently waste tokens. micro-x should default to depth 1 with an opt-in depth-2 orchestrator mode, and treat `max_turns` / step tracking as a safety net rather than the primary depth control.

### 10. Checkpointing and resume are production-critical

LangGraph makes the strongest case for checkpointing: full state persistence at every super-step enables resume from any point, human-in-the-loop at arbitrary graph positions, and debugging via state inspection. OpenClaw's JSONL transcripts and OpenAI's sessions serve similar but less powerful purposes. micro-x should support checkpoint-based resume from the start, especially for multi-agent workflows.

### 11. Graph visualization and structural inspection aid debugging

LangGraph's Mermaid diagrams and LangGraph Studio demonstrate the value of being able to visualize multi-agent execution flow. When agents are structurally composed (rather than dynamically spawned), the entire topology is inspectable before execution. micro-x should support some form of agent topology visualization.

---

## Sources

- [Claude Code Sub-Agent Architecture](claude-code-subagent-architecture.md) -- companion research doc
- [OpenAI Agents SDK Multi-Agent Deep Research](openai-agents-sdk-multi-agent-deep-research.md) -- companion research doc
- [LangGraph Multi-Agent Deep Research](langgraph-multi-agent-deep-research.md) -- companion research doc
- [OpenClaw Sub-Agents](../openclaw-research/13-sub-agents.md)
- [OpenClaw Multi-Agent Routing](../openclaw-research/09-multi-agent.md)
- [OpenClaw Agent Loop](../openclaw-research/04-agent-loop.md)
- [OpenClaw Sessions and Memory](../openclaw-research/05-sessions-and-memory.md)
- [OpenClaw Sandboxing](../openclaw-research/12-sandboxing.md)
- [OpenClaw Exec and Approvals](../openclaw-research/14-exec-and-approvals.md)
- [Framework Comparison](../openclaw-research/22-framework-comparison.md)
- [Claude Agent SDK Architecture](claude-agent-sdk-architecture.md)
- [OpenAI Agents SDK -- Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [OpenAI Agents SDK -- Multi-Agent Orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [OpenAI Agents SDK -- Agents](https://openai.github.io/openai-agents-python/agents/)
- [OpenAI Agents SDK -- Guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenAI Agents SDK -- Tracing](https://openai.github.io/openai-agents-python/tracing/)
- [LangGraph Official Documentation](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph Multi-Agent Workflows](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- [LangGraph Subgraphs Documentation](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangGraph Interrupts Documentation](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Streaming Documentation](https://docs.langchain.com/oss/python/langgraph/streaming)
- [LangGraph Memory Documentation](https://docs.langchain.com/oss/python/langgraph/memory)
