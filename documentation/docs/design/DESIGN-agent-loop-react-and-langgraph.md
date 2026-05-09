# Design: Agent Loop — Stop Conditions, ReAct Lineage, and LangGraph Comparison

This document is a conceptual companion to [DESIGN-agent-loop.md](DESIGN-agent-loop.md) and [agent-loop-tool-calls.md](agent-loop-tool-calls.md). Those docs describe *how* the loop works; this one explains *when it stops*, *what pattern it implements*, and *how it differs from LangGraph's equivalent*.

## Stop conditions

The loop body lives in `TurnEngine.run` at `src/micro_x_agent_loop/turn_engine.py:136` (`while True:`). It exits via `return` in two cases, with one extra retry path that delays exit.

### Normal exit — model returned no tool calls

`turn_engine.py:252-253`

After each `provider.stream_chat`, the engine inspects `tool_use_blocks`. If the assistant's reply contains none, the turn ends and the assistant text is the final answer. This is the structural equivalent of an `end_turn` stop reason.

### Hard stop — repeated `max_tokens` truncation

`turn_engine.py:229-238`

If the provider returns `stop_reason == "max_tokens"` *and* there were no tool calls, the engine treats this as a truncated reply. It appends a "be more concise / continue" nudge and loops again. A `max_tokens_attempts` counter increments each time. Once it reaches `MAX_TOKENS_RETRIES` (constant in `constants.py`), the engine emits an error through the channel and returns.

When `max_tokens` truncation occurs alongside tool calls, the tools still execute and the loop continues — the counter only applies to pure-text truncations.

### Continue (does NOT stop)

Any tool-use blocks present cause the loop to:

1. Classify blocks into 5 buckets (`turn_engine.py:255-272`): `tool_search` / `ask_user` / `spawn_subagent` / `task_*` / regular MCP tools.
2. Execute pseudo-tools inline; execute regular tools in parallel via `asyncio.gather`.
3. Append `tool_result` blocks to the conversation.
4. `turn_iteration += 1` and loop.

### Outer guard — session budget

`agent.py:342-350`, `Agent._is_budget_exceeded`

`Agent._run_inner` refuses to *start* a new turn if `SessionBudgetUSD` has been hit. This is per-user-turn, not per-iteration — it does not interrupt the loop mid-turn.

## Relationship to ReAct

The loop implements the **structural** ReAct pattern, not the **textual** one.

**Original ReAct** (Yao et al., 2022) interleaves explicit `Thought:` / `Action:` / `Observation:` text in a single prompt stream. Reasoning is verbalized as text; the harness parses those markers to drive the loop.

**This codebase** uses the modern descendant — sometimes called the *agentic tool-use loop* — that almost every current framework (LangGraph's `create_react_agent`, OpenAI's Assistants/Responses runs, Claude's agent loop) implements:

| ReAct concept | Surface in this codebase |
|---|---|
| `Thought:` | Whatever text the assistant emits alongside tool-use blocks (and optional Anthropic extended-thinking blocks) |
| `Action:` | A structured `tool_use` block from the provider API |
| `Observation:` | A `tool_result` content block appended as a user message |
| `Finish[answer]` | Assistant message with no tool-use blocks → `return` |

Some literature still calls this ReAct loosely; purists reserve "ReAct" for the prompted-thought variant. Either way, the *control-flow shape* is identical: call model → if it wants tools, run them, feed results back, repeat; otherwise stop.

### Beyond ReAct

The codebase extends the basic pattern with an orchestration layer ReAct did not contemplate:

- **Pseudo-tools** handled inline in the engine, never dispatched to MCP: `tool_search`, `ask_user`, `spawn_subagent`, `task_create` / `task_update` / `task_list` / `task_get`.
- **Per-iteration model routing** via `RoutingStrategy.decide(...)` (`turn_engine.py:159-178`) — provider/model can change between iterations of the same turn, optionally pinned by `pin_continuation`.
- **Dynamic tool list** — `tool_search_manager.get_tools_for_api_call()` returns only loaded tools, narrowing the API payload to fit small-context models.
- **Inline conversation compaction** — `await self._events.on_maybe_compact()` runs before each LLM call and after each tool batch.
- **File-mutation checkpoints** captured before tool execution, enabling `/rewind` to restore working-tree state.

## Comparison with LangGraph

### LangGraph in one minute

LangGraph (LangChain) models an agent as a **directed graph**, not a loop:

- **State** — a typed dict (`TypedDict` / Pydantic). Nodes return *partial* updates; LangGraph merges them via per-field **reducers** (e.g. `messages` uses `add_messages` to append).
- **Nodes** — functions `state -> partial_state`. The canonical ReAct agent has two: an `agent` node that calls the LLM, and a `ToolNode` that runs whatever tools the last assistant message asked for.
- **Edges** — static (`A -> B`) or **conditional**. `tools_condition` inspects the last message: if it contains `tool_calls`, route to `tools`; else route to `END`.
- **Checkpointer** — `MemorySaver` / `SqliteSaver` / `PostgresSaver` snapshots state at every node boundary, keyed by a `thread_id`. Enables resume, time-travel, and forking for free.
- **Interrupts** — `interrupt_before=["tools"]` pauses at a node; resume with `Command(resume=...)`. This is the HITL primitive.
- **Streaming** — `graph.stream(..., stream_mode="updates"|"values"|"messages")` yields per-node deltas.
- **Subgraphs** — a graph can be a node inside another graph.

`create_react_agent` is roughly thirty lines: two nodes, one conditional edge.

### Where this codebase diverges

| Concern | LangGraph `create_react_agent` | This codebase |
|---|---|---|
| **Control flow** | Graph: `agent ↔ tools`, conditional edge `tools_condition` | Imperative `while True` (`turn_engine.py:136`) |
| **State** | Typed dict, merged via reducers; immutable per node | `messages: list[dict]` mutated in place + a `TurnEvents` callback protocol (`on_append_message`, `on_tool_started`, …) |
| **Tool dispatch** | One `ToolNode` runs everything | Five categories classified at `turn_engine.py:255-272`. Pseudo-tools execute **inline in the engine**, never through MCP |
| **Stop condition** | `tools_condition` returns `END` when `last.tool_calls` is empty | `if not tool_use_blocks: return` (`turn_engine.py:252`) — semantically identical |
| **Checkpointing** | Snapshots **whole state** at every node boundary, keyed by `thread_id`. Free time-travel | Snapshots only **filesystem mutations**, just before tool execution (`on_ensure_checkpoint_for_turn`, `turn_engine.py:337`). Rewind restores files and truncates messages; no state-graph time travel |
| **HITL** | `interrupt()` + `Command(resume=...)` — pauses the graph, persists state, awaits external input | `ask_user` is a normal pseudo-tool: the loop awaits `channel.ask_user(...)` synchronously (`turn_engine.py:289-303`). The asyncio task simply blocks |
| **Subagents** | Subgraphs — same state machinery, composed | `spawn_subagent` pseudo-tool runs a separate `SubAgentRunner`, which has its own `TurnEngine`. Not graph-composed |
| **Routing** | One model per agent, or a custom router node | Per-iteration `RoutingStrategy.decide(...)` (`turn_engine.py:159-178`) picks provider/model, can narrow tools, can override system prompt, can pin the choice for the rest of the turn |
| **Tool list** | Static at graph-build time | Dynamic per iteration via `tool_search_manager.get_tools_for_api_call()` (`turn_engine.py:140-150`) |
| **Compaction** | No built-in story — write a node | `await self._events.on_maybe_compact()` called before each LLM call and after each tool batch (`turn_engine.py:127, 357`) |
| **Truncation retry** | None — `max_tokens` finish ends the run | Self-nudge with retry budget (`turn_engine.py:229-248`) |
| **Streaming** | Per-node state deltas | Per-token + per-tool-lifecycle via `AgentChannel` (`emit_tool_started/completed`) |

### Trade-off summary

The **shape** of the loop is the same in both: ReAct without printed `Thought:` lines.

LangGraph's value-add is the **graph abstraction itself** — durable state, free checkpointing, free interrupts, declarative composition. The cost is ceremony: TypedDicts, reducers, `Command` objects, `thread_id` plumbing.

This codebase pays none of that ceremony and instead bakes domain features directly into the loop body: per-iteration cost-aware routing, dynamic tool narrowing via `tool_search`, file-level checkpoints (not state-level), inline pseudo-tools, and conversation compaction. The trade is **less topological generality** (you cannot swap the shape by editing edges) for **more leverage on the things this agent specifically does**.

A LangGraph port of this loop would not struggle with the loop itself — that is `create_react_agent`. The painful parts would be: re-expressing per-iteration routing as a node, modeling pseudo-tools as either nodes or as a custom `ToolNode` subclass, and reconciling the file-mutation checkpoint model with LangGraph's state-snapshot checkpointer.

## See also

- [DESIGN-agent-loop.md](DESIGN-agent-loop.md) — full loop design including voice, commands, compaction wiring
- [agent-loop-tool-calls.md](agent-loop-tool-calls.md) — tool-call mechanics inside the loop
- [DESIGN-cache-preserving-tool-routing.md](DESIGN-cache-preserving-tool-routing.md) — `pin_continuation` and routing-decision details
- [DESIGN-task-decomposition.md](DESIGN-task-decomposition.md) — `task_*` pseudo-tools
- [DESIGN-tool-system.md](DESIGN-tool-system.md) — `tool_search` and the dynamic tool list
