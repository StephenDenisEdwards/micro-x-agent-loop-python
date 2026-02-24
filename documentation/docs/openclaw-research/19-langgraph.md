# LangGraph

LangGraph is a graph-based orchestration framework by LangChain for building stateful, multi-agent systems. Workflows are modeled as directed graphs where nodes are computation steps and edges define transitions.

## Core architecture

Three primitives: **nodes**, **edges**, and **state**.

`StateGraph` is the primary class. You parameterize it with a typed state object, add nodes and edges, then call `.compile()` to produce a `CompiledGraph` (extends `Pregel` internally).

- **Nodes**: Python functions that receive current state, perform computation, return partial state updates
- **Edges**: Transitions between nodes — normal (unconditional), conditional (routing function), or entry (from `START`)
- **State**: Typed dictionary flowing through the graph. Keys can have **reducers** (e.g., `operator.add` for messages list) controlling how updates merge

## Agent loop (Pregel execution model)

Not a simple while-loop — it's a **graph traversal** in discrete **super-steps** (Bulk Synchronous Parallel model):

1. **Plan**: Determine which nodes are active (have pending state on incoming channels)
2. **Execute**: Run all active nodes **in parallel** within a super-step
3. **Update**: Apply outputs to state channels using reducers
4. **Checkpoint**: Persist snapshot of entire state
5. **Repeat** until no active nodes (graph reaches `END`)

For a ReAct agent, this creates a cycle:
```
assistant -> [tool calls?] -> tools -> assistant -> ... -> END
```

Functionally equivalent to a while-loop but with checkpointing, interrupt/resume, parallel execution, and typed state at every step.

## Tool system

Built on LangChain abstractions:

- **Defining**: `@tool` decorator extracts name, docstring, type hints for schema
- **Binding**: `llm.bind_tools(tools)` instructs model to produce structured `tool_calls`
- **ToolNode** (prebuilt): Reads `AIMessage`, extracts tool calls, dispatches to matching functions, returns `ToolMessage` objects
- **tools_condition** (prebuilt): Routes to tool node if tool calls present, else to `END`
- **create_react_agent** (prebuilt): Wires up full ReAct pattern in one call

## State management and checkpointing

Every super-step automatically persists a **checkpoint** — complete state snapshot scoped to a **thread**.

Enables:
- **Session persistence**: Resume after process restarts
- **Fault tolerance**: Resume from last successful checkpoint
- **Time travel**: Replay or fork from any historical checkpoint
- **Human-in-the-loop**: Pause, present state to human, resume

Backends: `InMemorySaver` (dev), SQLite, PostgreSQL, Redis, MongoDB.

## Multi-agent patterns

### Supervisor (`langgraph-supervisor`)
Central LLM-based supervisor delegates to specialized workers. All communication flows through supervisor.

### Hierarchical
Multi-level supervisors — top-level delegates to mid-level supervisors managing their own workers.

### Swarm (`langgraph-swarm`)
Decentralized — agents hand off via `transfer_to_X` tool calls. No central coordinator. Inspired by OpenAI's Swarm concept.

### Network / Shared-workspace
Agents share common state and contribute asynchronously. Parallel execution in same super-step.

## Memory

Three tiers:

### Short-term (thread-scoped)
Conversation state within a thread. Managed by checkpointer. `messages` list accumulates full history.

### Long-term (cross-thread, via Store)
Persistent key-value document store not scoped to a thread. Organized into namespaces (e.g., `("user", user_id, "preferences")`). Supports `put`, `get`, `search`, `delete`. Content-based filtering/search.

### Cross-thread persistence
Data saved in thread A under namespace `("user", "alice")` retrievable in thread B with same namespace. Enables user profiles and accumulated knowledge across sessions.

## Human-in-the-loop

### Static breakpoints
```python
graph = builder.compile(checkpointer=checkpointer, interrupt_before=["tools"])
```

### Dynamic interrupts
```python
from langgraph.types import interrupt, Command
approval = interrupt({"question": "Approve this action?"})
```

Resume with `Command` object containing resume value and optional `goto` directive.

## Streaming

Five modes (combinable):
1. **`values`**: Full state after each super-step
2. **`updates`**: Partial state updates per node
3. **`messages`**: Individual LLM tokens as generated
4. **`events`**: All internal LangChain events (most granular)
5. **`custom`**: Arbitrary events from nodes

## Deployment

| Tier | Description |
|------|-------------|
| **Open source** | Core library (MIT). You manage infrastructure |
| **LangGraph Server** | Production runtime with HTTP/WS APIs, task queues, horizontal scaling, cron |
| **LangGraph Cloud** | Managed SaaS or BYOC. Monitoring via LangSmith |

## Comparison with a simple while-loop

| Dimension | While-loop | LangGraph |
|-----------|-----------|-----------|
| Control flow | Implicit if/else | Declarative graph edges |
| State | Ad-hoc variables | Typed schema with reducers |
| Persistence | None | Checkpointing at every step |
| Fault tolerance | Crash = start over | Resume from checkpoint |
| Human-in-the-loop | Build yourself | First-class `interrupt()` + breakpoints |
| Streaming | Manual | 5 built-in modes |
| Multi-agent | Manual coordination | Supervisor, swarm, hierarchical patterns |
| Parallelism | Sequential | Automatic within super-steps |
| Complexity | Minimal | Significant (graphs, reducers, Pregel model) |

## Key references

- [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- [GitHub: langgraph](https://github.com/langchain-ai/langgraph)
- [GitHub: langgraph-supervisor-py](https://github.com/langchain-ai/langgraph-supervisor-py)
- [GitHub: langgraph-swarm-py](https://github.com/langchain-ai/langgraph-swarm-py)
- [Comparing frameworks (Langfuse)](https://langfuse.com/blog/2025-03-19-ai-agent-comparison)
