# LangGraph Multi-Agent & Sub-Agent Deep Research

> **Date:** 2026-02-26
> **Subject:** Comprehensive deep-dive into LangGraph's multi-agent architecture patterns, subgraph composition, handoffs, state management, and coordination primitives
> **Sources:** Official LangGraph docs, GitHub repos (langgraph, langgraph-supervisor-py, langgraph-swarm-py), LangChain blog posts, community references
> **Complements:** [langgraph-architecture.md](./langgraph-architecture.md) (general architecture research)

---

## Table of Contents

1. [Multi-Agent Architecture Patterns](#1-multi-agent-architecture-patterns)
2. [Subgraph Composition](#2-subgraph-composition)
3. [Handoffs and Transfers](#3-handoffs-and-transfers)
4. [State Management Across Agents](#4-state-management-across-agents)
5. [Supervisor Pattern](#5-supervisor-pattern)
6. [Human-in-the-Loop Across Agent Boundaries](#6-human-in-the-loop-across-agent-boundaries)
7. [Checkpointing Across Agents](#7-checkpointing-across-agents)
8. [Streaming Across Agents](#8-streaming-across-agents)
9. [Tool Access and Scoping](#9-tool-access-and-scoping)
10. [Concurrency and Parallelism](#10-concurrency-and-parallelism)
11. [Memory and Persistence](#11-memory-and-persistence)
12. [Prebuilt Components](#12-prebuilt-components)
13. [Comparison: LangGraph vs OpenAI Handoffs](#13-comparison-langgraph-vs-openai-handoffs)
14. [Key Takeaways for Our Design](#14-key-takeaways-for-our-design)

---

## 1. Multi-Agent Architecture Patterns

LangGraph supports multiple multi-agent architecture patterns, each with distinct coordination models, communication strategies, and tradeoffs.

### 1.1 Core Design Principle

LangGraph enables **"multiple independent actors powered by language models connected in a specific way."** Each agent has its own prompt, LLM, tools, and custom code. Two fundamental questions define any multi-agent system:

1. **What are the independent agents?** (nodes in the graph)
2. **How are agents connected?** (edges defining control flow and communication)

### 1.2 Supervisor Pattern

A central supervisor agent coordinates specialized sub-agents through tool-based delegation.

```
                    ┌──────────────┐
                    │  Supervisor  │
                    │   (router)   │
                    └──────┬───────┘
                ┌──────────┼──────────┐
                ▼          ▼          ▼
         ┌──────────┐ ┌──────────┐ ┌──────────┐
         │ Agent A  │ │ Agent B  │ │ Agent C  │
         │(calendar)│ │ (email)  │ │(research)│
         └──────────┘ └──────────┘ └──────────┘
```

**Characteristics:**
- Independent scratchpads per agent; final responses merged to global scratchpad
- Supervisor acts as the orchestrator -- "can be thought of as an agent whose tools are other agents"
- Sub-agents are invoked via tool calls, not direct graph edges
- Supervisor consistently uses more tokens than swarm because it must "translate" between sub-agents and the user

**When to use:** Multiple distinct domains (calendar, email, CRM), centralized workflow control needed, sub-agents don't require direct user conversation.

### 1.3 Swarm Pattern

Decentralized approach where agents operate with greater autonomy, using **handoff tools** to transfer control directly between each other.

```
         ┌──────────┐         ┌──────────┐
         │  Alice   │ ──────▶ │   Bob    │
         │ (travel) │ ◀────── │(bookings)│
         └──────────┘         └──────────┘
              │                     │
              ▼                     ▼
         ┌──────────┐         ┌──────────┐
         │  Carol   │         │  Dave    │
         │(payments)│         │(customer)│
         └──────────┘         └──────────┘
```

**Characteristics:**
- Agents transfer control via `create_handoff_tool()` -- peer-to-peer, no central supervisor
- Tracks `active_agent` in state; conversations resume with last active agent
- Reduced bottlenecks; greater parallelization potential
- More emergent problem-solving behavior

**State schema:**
```python
class SwarmState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    active_agent: str
```

### 1.4 Hierarchical Teams

Supervisors manage other supervisors, creating nested hierarchies for complex organizations.

```
                    ┌──────────────────┐
                    │  Top Supervisor  │
                    └───────┬──────────┘
                   ┌────────┴────────┐
                   ▼                 ▼
            ┌──────────┐      ┌──────────┐
            │ Research  │      │ Writing  │
            │Supervisor │      │Supervisor│
            └────┬─────┘      └────┬─────┘
              ┌──┴──┐           ┌──┴──┐
              ▼     ▼           ▼     ▼
           [web] [arxiv]     [draft] [edit]
```

**Characteristics:**
- Each team is a sub-graph with its own supervisor
- Teams can have different state schemas
- Greater flexibility than flat supervisor patterns
- Sub-supervisors are LangGraph sub-agents (not just AgentExecutors)

### 1.5 Network (Collaboration) Topology

All agents share a common scratchpad and communicate through shared state.

**Characteristics:**
- Full transparency of intermediate steps
- Communication via shared scratchpad of messages visible to all agents
- Rule-based router checks LLM output for tool invocation
- Can be verbose with information passing

### 1.6 Pattern Comparison

| Pattern | Control Flow | Communication | Scalability | Token Usage | Complexity |
|---------|-------------|---------------|-------------|-------------|------------|
| **Supervisor** | Centralized | Through supervisor | Medium | Higher (translation overhead) | Medium |
| **Swarm** | Decentralized | Direct peer-to-peer | High | Lower | Lower |
| **Hierarchical** | Hierarchical | Through team supervisors | Very High | Highest | Highest |
| **Network** | Flat/shared | Shared scratchpad | Low | Variable | Low |

---

## 2. Subgraph Composition

Subgraphs are the fundamental building block for multi-agent systems in LangGraph. A subgraph is a **compiled graph that functions as a node** within a parent graph.

### 2.1 Two Integration Patterns

#### Pattern A: Direct Node Addition (Shared State Keys)

When parent and subgraph share identical state keys (especially `messages`), pass the compiled subgraph directly to `add_node()`:

```python
from langgraph.graph import StateGraph, MessagesState, START, END

# Define the subgraph
subgraph_builder = StateGraph(MessagesState)
subgraph_builder.add_node("sub_node_a", sub_node_a_fn)
subgraph_builder.add_node("sub_node_b", sub_node_b_fn)
subgraph_builder.add_edge(START, "sub_node_a")
subgraph_builder.add_edge("sub_node_a", "sub_node_b")
subgraph_builder.add_edge("sub_node_b", END)
subgraph = subgraph_builder.compile()

# Add directly as a node in parent graph
parent_builder = StateGraph(MessagesState)
parent_builder.add_node("my_subgraph", subgraph)  # CompiledGraph as node
parent_builder.add_edge(START, "my_subgraph")
parent_builder.add_edge("my_subgraph", END)
parent = parent_builder.compile()
```

**Key behavior:** The subgraph reads from and writes to the parent's state channels automatically. No wrapper function is needed. When the subgraph completes, **only overlapping keys** are surfaced back to the parent. Any subgraph-only keys remain internal and do not leak into parent state.

#### Pattern B: Invocation Inside a Node Function (Different Schemas)

When parent and subgraph have **different state schemas** (no shared keys), wrap the subgraph call in a transformation function:

```python
class SubgraphState(TypedDict):
    bar: str
    baz: str  # internal to subgraph

class ParentState(TypedDict):
    foo: str

def call_subgraph(state: ParentState):
    # Transform parent state -> subgraph input
    subgraph_output = subgraph.invoke({"bar": state["foo"]})
    # Transform subgraph output -> parent state update
    return {"foo": subgraph_output["bar"]}

parent_builder = StateGraph(ParentState)
parent_builder.add_node("my_subgraph", call_subgraph)
```

**Key behavior:** Complete isolation. The node function explicitly maps fields between schemas. Child keys (like `baz`) are never accessible at the parent level.

### 2.2 Multi-Level Nesting (Grandchild Subgraphs)

LangGraph supports arbitrary nesting depth. Each level transforms state at boundaries:

```python
# Grandchild graph
class GrandchildState(TypedDict):
    my_grandchild_key: str

grandchild_builder = StateGraph(GrandchildState)
# ... add nodes and edges ...
grandchild_graph = grandchild_builder.compile()

# Child graph wraps grandchild
class ChildState(TypedDict):
    my_child_key: str

def call_grandchild(state: ChildState) -> ChildState:
    grandchild_input = {"my_grandchild_key": state["my_child_key"]}
    grandchild_output = grandchild_graph.invoke(grandchild_input)
    return {"my_child_key": grandchild_output["my_grandchild_key"] + " today?"}

child_builder = StateGraph(ChildState)
child_builder.add_node("grandchild", call_grandchild)
child_graph = child_builder.compile()

# Parent graph wraps child
class ParentState(TypedDict):
    my_key: str

def call_child(state: ParentState) -> ParentState:
    child_input = {"my_child_key": state["my_key"]}
    child_output = child_graph.invoke(child_input)
    return {"my_key": child_output["my_child_key"]}

parent_builder = StateGraph(ParentState)
parent_builder.add_node("child", call_child)
```

**Isolation principle:** Child or grandchild keys are never accessible at the parent level. Each boundary requires explicit transformation.

### 2.3 Namespace Isolation for Stateful Subagents

When multiple stateful subagents need parallel execution, each must have a unique namespace to prevent checkpoint conflicts:

```python
def create_sub_agent(model, *, name, **kwargs):
    """Wrap each agent in its own StateGraph with a unique node name."""
    agent = create_agent(model=model, name=name, **kwargs)
    return (
        StateGraph(MessagesState)
        .add_node(name, agent)  # unique name -> stable namespace
        .add_edge("__start__", name)
        .compile()
    )

fruit_agent = create_sub_agent(model, name="fruit_expert", tools=[fruit_tool])
veggie_agent = create_sub_agent(model, name="veggie_expert", tools=[veggie_tool])
```

**Critical:** If you call subgraphs inside a node, LangGraph assigns namespaces based on call order (first call, second call, etc.). Wrapping in named StateGraphs gives stable, predictable namespaces.

### 2.4 Inspecting and Streaming Subgraph State

```python
# View subgraph state
subgraph_state = graph.get_state(config, subgraphs=True).tasks[0].state

# Stream with subgraph outputs
for chunk in graph.stream(
    {"foo": "bar"},
    subgraphs=True,
    stream_mode="updates"
):
    print(chunk)
```

---

## 3. Handoffs and Transfers

Handoffs are the mechanism by which control transfers from one agent to another. LangGraph provides both low-level primitives (`Command`) and high-level utilities (`create_handoff_tool`).

### 3.1 The `Command` Object

`Command` is the fundamental primitive for combining state updates and control flow routing in a single return value:

```python
from langgraph.types import Command
from typing import Literal

def my_node(state: State) -> Command[Literal["agent_a", "agent_b"]]:
    if state["foo"] == "bar":
        return Command(
            update={"foo": "baz"},
            goto="agent_a"
        )
    return Command(
        update={"foo": "qux"},
        goto="agent_b"
    )
```

**Key properties:**
- `update`: Dictionary of state changes to apply
- `goto`: Target node name (or list of node names) for routing
- `graph`: Optional -- set to `Command.PARENT` to route to parent graph level

**Important behavior:** Command routing is **additive** to static edges. "Command doesn't override static edges" -- the node will execute to both Command destinations AND statically-defined edges.

### 3.2 `Command.PARENT` -- Cross-Graph Navigation

A node inside a subgraph can direct control to another node in the parent graph:

```python
def agent_alice_node(state: AgentState) -> Command[Literal["bob"]]:
    """Hand off from Alice's subgraph to Bob (another node in parent graph)."""
    return Command(
        goto="bob",
        update={
            "messages": [AIMessage(content="Handing off to Bob")],
        },
        graph=Command.PARENT  # Navigate up to parent graph
    )
```

**Requirement:** When sending updates from a subgraph to a parent graph for a shared key, you **must** define a reducer for that key in the parent graph state schema.

### 3.3 `create_handoff_tool` (langgraph-supervisor)

A factory function that creates tools enabling agent-to-agent delegation:

```python
from langgraph_supervisor import create_handoff_tool

# Basic usage
handoff_to_research = create_handoff_tool(
    agent_name="research_agent",
    name="transfer_to_research",        # optional custom name
    description="Transfer to research"  # optional custom description
)
```

**Default behavior:**
- Passes the **full message history** (all messages up to the handoff point) to the receiving agent
- Appends a `ToolMessage` confirming the successful handoff
- Returns `Command(goto=[Send(agent_name, state)])` for parallel handoffs

**Performance consideration:** The default passes the entire conversation history, which can become huge for long conversations, leading to slower execution. For optimization, consider custom handoff tools that summarize or truncate context.

### 3.4 Tool-Based Handoff Pattern (Manual)

You can implement handoffs manually using the `@tool` decorator:

```python
from langchain.tools import tool, ToolRuntime
from langchain.messages import ToolMessage, AIMessage
from langgraph.types import Command

@tool
def transfer_to_sales(runtime: ToolRuntime) -> Command:
    """Transfer conversation to the sales agent."""
    last_ai_message = next(
        msg for msg in reversed(runtime.state["messages"])
        if isinstance(msg, AIMessage)
    )
    transfer_message = ToolMessage(
        content="Transferred to sales agent",
        tool_call_id=runtime.tool_call_id
    )
    return Command(
        goto="sales_agent",
        update={
            "active_agent": "sales_agent",
            "messages": [last_ai_message, transfer_message]
        },
        graph=Command.PARENT
    )
```

**Critical requirement:** Always include a `ToolMessage` with matching `tool_call_id` to complete the request-response cycle and maintain valid conversation history.

### 3.5 Two Architectural Approaches to Handoffs

#### Approach 1: Single Agent with Middleware (State-Variable Handoffs)

One agent with dynamic configuration; a `current_step` state variable controls behavior:

```python
class SupportState(AgentState):
    current_step: str = "triage"
    warranty_status: str | None = None

@tool
def transfer_to_specialist(runtime: ToolRuntime) -> Command:
    """Transfer to specialist."""
    return Command(
        update={
            "messages": [ToolMessage(
                content="Transferred to specialist",
                tool_call_id=runtime.tool_call_id
            )],
            "current_step": "specialist"
        }
    )
```

Middleware intercepts model calls to adjust prompts and tools based on `current_step`:

```python
@wrap_model_call
def apply_step_config(request: ModelRequest, handler) -> ModelResponse:
    step = request.state.get("current_step", "triage")
    configs = {
        "triage": {"prompt": "Collect info...", "tools": [record_status]},
        "specialist": {"prompt": "Provide solutions...", "tools": [solve]}
    }
    config = configs[step]
    request = request.override(system_prompt=config["prompt"], tools=config["tools"])
    return handler(request)
```

#### Approach 2: Multiple Agent Subgraphs

Separate agents as distinct graph nodes. Each returns `Command(graph=Command.PARENT)` to hand off:

```python
# Agent A subgraph
def agent_a_node(state):
    # ... agent logic ...
    return Command(goto="agent_b", graph=Command.PARENT)

# Agent B subgraph
def agent_b_node(state):
    # ... agent logic ...
    return Command(goto=END, graph=Command.PARENT)
```

**When to use Approach 1 vs 2:**
- Approach 1 (middleware): Simpler, fewer state transitions, recommended for most cases
- Approach 2 (subgraphs): When agents have fundamentally different architectures, tools, or state requirements

---

## 4. State Management Across Agents

### 4.1 StateGraph, Channels, and Reducers

**StateGraph** is the primary graph implementation accepting a user-defined state schema:

```python
from langgraph.graph import StateGraph
from typing import Annotated, TypedDict
from operator import add

class State(TypedDict):
    foo: int
    bar: Annotated[list[str], add]  # Custom reducer: appends
```

**Channels** are the individual keys in the state schema. Each key is an independent channel with its own reducer:

- **Default reducer:** Overwrites the existing value
- **Custom reducer:** Specified via `Annotated[type, reducer_function]`

```python
# Without reducer -- overwrites
class State(TypedDict):
    messages: list[str]

# With add reducer -- appends
class State(TypedDict):
    messages: Annotated[list[str], add]

# With add_messages -- intelligent message handling (dedup by ID, etc.)
from langgraph.graph.message import add_messages
class State(TypedDict):
    messages: Annotated[list, add_messages]
```

### 4.2 The `MessagesState` Convenience Class

Pre-built state schema with the `messages` key and `add_messages` reducer:

```python
from langgraph.graph import MessagesState

class State(MessagesState):
    documents: list[str]  # Extend with custom fields
```

### 4.3 Multiple Schemas (Input, Output, Internal)

Graphs support distinct schemas for input, output, and internal state:

```python
class InputState(TypedDict):
    user_input: str

class OutputState(TypedDict):
    graph_output: str

class OverallState(TypedDict):
    foo: str
    user_input: str
    graph_output: str

builder = StateGraph(
    OverallState,
    input_schema=InputState,
    output_schema=OutputState
)
```

**Key insight:** Nodes can write to **any** state channel in the graph state, regardless of input schema restrictions. The input schema only restricts what comes in from the caller; the output schema only restricts what goes out.

### 4.4 State Flow Between Parent and Child Graphs

**Shared keys (Pattern A):**
- Parent writes state -> subgraph reads overlapping keys automatically
- Subgraph writes state -> parent receives overlapping keys automatically
- Subgraph-only keys remain internal (never leak to parent)

**Different schemas (Pattern B):**
- Node function explicitly maps parent state -> subgraph input
- Node function explicitly maps subgraph output -> parent state update
- Complete isolation between schemas

**Cross-graph state updates (via Command):**
- When using `Command(graph=Command.PARENT)`, the `update` dict applies to the **parent** graph's state
- You must define reducers on the parent for any shared keys being updated from a subgraph

### 4.5 Super-Steps and State Merging

LangGraph executes in **super-steps** -- batches of concurrent node executions:

1. All active nodes execute concurrently within a super-step
2. Reducers merge the outputs from all nodes in that super-step
3. State is checkpointed
4. The merged state flows to the next set of active nodes

This means multiple parallel nodes can safely write to the same state key (e.g., a list with an `add` reducer) without conflicts.

---

## 5. Supervisor Pattern

### 5.1 The Recommended Approach: Agents-as-Tools

The officially recommended supervisor pattern wraps sub-agents as **tools** that the supervisor can invoke:

```python
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

model = init_chat_model("claude-haiku-4-5-20251001")

# Step 1: Create specialized sub-agents
calendar_agent = create_agent(
    model,
    tools=[create_calendar_event, get_available_time_slots],
    system_prompt="You are a calendar scheduling assistant..."
)

email_agent = create_agent(
    model,
    tools=[send_email],
    system_prompt="You are an email assistant..."
)

# Step 2: Wrap sub-agents as tools
@tool
def schedule_event(request: str) -> str:
    """Schedule calendar events using natural language."""
    result = calendar_agent.invoke({
        "messages": [{"role": "user", "content": request}]
    })
    return result["messages"][-1].text

@tool
def manage_email(request: str) -> str:
    """Send emails using natural language."""
    result = email_agent.invoke({
        "messages": [{"role": "user", "content": request}]
    })
    return result["messages"][-1].text

# Step 3: Create the supervisor
supervisor_agent = create_agent(
    model,
    tools=[schedule_event, manage_email],
    system_prompt=(
        "You are a helpful personal assistant. "
        "Break down user requests into appropriate tool calls."
    )
)
```

**Architecture:** Three-layer system -- supervisor sees high-level tools and makes routing decisions at the domain level, not the individual API level. Sub-agents have their own focused prompts and API-level tools.

### 5.2 Using `create_supervisor` (langgraph-supervisor library)

```python
from langgraph_supervisor import create_supervisor

workflow = create_supervisor(
    agents=[calendar_agent, email_agent, research_agent],
    model=model,
    prompt="You are a helpful assistant that delegates tasks...",
    supervisor_name="supervisor",
    tools=[],                          # Additional supervisor-only tools
    output_mode="full_history",        # or "last_message"
    handoff_tool_prefix="transfer_to",
    add_handoff_messages=True
)

app = workflow.compile(checkpointer=checkpointer)
```

**Output modes:**
| Mode | Behavior |
|------|----------|
| `"full_history"` | Includes all agent messages in supervisor history |
| `"last_message"` | Retains only the final agent response |

**Note:** LangChain now recommends using the agents-as-tools pattern directly rather than this library for most use cases, as it gives more control over context engineering.

### 5.3 Tool-Based Routing vs Conditional Edges

**Tool-based routing (recommended):**
- Supervisor calls agent-tools via LLM tool-calling
- Routing decisions are made by the LLM based on tool descriptions
- More flexible and natural for the LLM
- Sub-agents are invoked as regular tool calls

**Conditional edges (manual routing):**
- Routing function inspects state and returns the next node name
- Deterministic, rule-based routing
- More predictable but less flexible

```python
# Conditional edge approach
def route_decision(state: State) -> Literal["calendar", "email", "end"]:
    if "schedule" in state["messages"][-1].content.lower():
        return "calendar"
    elif "email" in state["messages"][-1].content.lower():
        return "email"
    return "end"

builder.add_conditional_edges("supervisor", route_decision)
```

**When to use Command vs conditional edges:**
- `Command`: When needing simultaneous state updates AND routing
- Conditional edges: Pure routing without state modification

### 5.4 Passing Context to Sub-Agents

Sub-agents wrapped as tools can receive the full conversation context via `ToolRuntime`:

```python
from langchain.tools import tool, ToolRuntime

@tool
def schedule_event(request: str, runtime: ToolRuntime) -> str:
    """Schedule calendar events with full conversation context."""
    original_user_message = next(
        msg for msg in runtime.state["messages"]
        if msg.type == "human"
    )
    prompt = (
        f"User inquiry: {original_user_message.text}\n\n"
        f"Sub-request: {request}"
    )
    result = calendar_agent.invoke({
        "messages": [{"role": "user", "content": prompt}]
    })
    return result["messages"][-1].text
```

---

## 6. Human-in-the-Loop Across Agent Boundaries

### 6.1 The `interrupt()` Function

`interrupt()` pauses graph execution at any point and returns a value to the caller:

```python
from langgraph.types import interrupt

def approval_node(state: State) -> Command[Literal["proceed", "cancel"]]:
    decision = interrupt({
        "question": "Approve this action?",
        "details": state["action_details"],
    })
    return Command(goto="proceed" if decision else "cancel")
```

**Requirements:**
- A checkpointer to persist graph state
- A thread ID in config: `{"configurable": {"thread_id": "..."}}`
- JSON-serializable payload

### 6.2 How Interrupts Work

1. Graph execution suspends at the `interrupt()` call
2. State is saved via the checkpointer
3. The payload value returns to the caller under the `__interrupt__` field
4. The graph waits **indefinitely** for resumption
5. The resume response becomes the `interrupt()` return value

**Critical behavior:** When a node resumes after an interrupt, the **node restarts from the beginning** of the node where `interrupt()` was called. Any code before `interrupt()` runs again.

### 6.3 Resuming with `Command`

```python
from langgraph.types import Command

config = {"configurable": {"thread_id": "thread-1"}}

# Initial run hits interrupt, pauses
result = graph.invoke({"input": "data"}, config=config)
print(result["__interrupt__"])  # Shows what's waiting

# Resume with response value
graph.invoke(Command(resume=True), config=config)
```

**Critical:** You must use the **same thread ID** when resuming.

### 6.4 Interrupts in Subgraphs

When a subgraph contains an `interrupt()` call:
- The **parent graph** resumes from the **beginning of the node** where the subgraph was invoked
- The **subgraph** also resumes from the beginning of its interrupted node
- Both levels restart -- code before `interrupt()` runs again at both levels

**Enable subgraph interrupt detection:** Use `subgraphs=True` when streaming or getting state:

```python
# Required for interrupt detection in nested graphs
for chunk in graph.stream(input, config, subgraphs=True):
    ...
```

### 6.5 Parallel Interrupts

When fan-out creates parallel branches that each call `interrupt()`, map interrupt IDs to resume values:

```python
interrupted_result = graph.invoke({"vals": []}, config)

resume_map = {
    i.id: f"answer for {i.value}"
    for i in interrupted_result["__interrupt__"]
}
result = graph.invoke(Command(resume=resume_map), config)
```

### 6.6 Interrupts in Tools

```python
@tool
def send_email(to: str, subject: str, body: str):
    """Send an email -- requires human approval."""
    response = interrupt({
        "action": "send_email",
        "to": to,
        "subject": subject,
        "body": body,
        "message": "Approve sending this email?"
    })
    if response.get("action") == "approve":
        return f"Email sent to {response.get('to', to)}"
    return "Email cancelled by user"
```

### 6.7 Static Breakpoints (Debugging)

Less recommended for production HITL; primarily for debugging:

```python
# Compile time
graph = builder.compile(
    interrupt_before=["node_a"],
    interrupt_after=["node_b", "node_c"],
    checkpointer=checkpointer,
)

# Runtime
graph.invoke(inputs, interrupt_before=["node_a"], config=config)

# Resume
graph.invoke(None, config=config)
```

### 6.8 Human-in-the-Loop with Middleware

For supervisor multi-agent systems, use `HumanInTheLoopMiddleware`:

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver

calendar_agent = create_agent(
    model,
    tools=[create_calendar_event],
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={"create_calendar_event": True},
            description_prefix="Calendar event pending approval"
        )
    ]
)

supervisor = create_agent(
    model,
    tools=[schedule_event, manage_email],
    checkpointer=InMemorySaver()  # Required for pause/resume
)
```

### 6.9 Critical Rules for Interrupts

**Do NOT:**
- Wrap `interrupt()` in bare `try/except` blocks (catches the interrupt exception)
- Reorder interrupt calls within a node between executions
- Conditionally skip interrupt calls based on state
- Pass non-serializable objects to `interrupt()`
- Perform non-idempotent side effects before `interrupt()`

**DO:**
- Keep interrupt call order consistent
- Place side effects **after** `interrupt()` calls
- Use idempotent operations (upsert, not insert) before interrupts
- Separate side effects into different nodes when possible

---

## 7. Checkpointing Across Agents

### 7.1 How Checkpoints Work with Subgraphs

**Parent graph checkpointer controls subgraph persistence.** The parent graph **must** be compiled with a checkpointer for subgraph persistence features (interrupts, state inspection, stateful memory) to work.

```python
from langgraph.checkpoint.memory import InMemorySaver

# Parent graph with checkpointer
parent = parent_builder.compile(checkpointer=InMemorySaver())
```

### 7.2 Stateless vs Stateful Subgraphs

**Stateless (default):** Each invocation starts fresh. Compile with `checkpointer=None` or omit.

```python
subgraph = subgraph_builder.compile()  # Stateless -- no memory between calls
```

- Right choice for most applications, including multi-agent systems where subagents handle independent requests
- Supports interrupts (parent checkpointer handles state saving)

**Stateful:** Conversation history accumulates across calls. Compile with `checkpointer=True`.

```python
subgraph = subgraph_builder.compile(checkpointer=True)
```

- Use when subagent needs multi-turn conversation memory
- **Limitation:** Stateful subgraphs do **not** support parallel calls to the same subagent (checkpoint namespace conflicts)
- Requires sequential calls or `ToolCallLimitMiddleware` to enforce single-call limits

### 7.3 Namespace Isolation

Each stateful subagent needs its own storage space so checkpoints don't overwrite each other:

```python
# Each agent gets a unique node name -> unique checkpoint namespace
def create_stateful_sub_agent(model, name, tools):
    agent = create_agent(model=model, name=name, tools=tools)
    return (
        StateGraph(MessagesState)
        .add_node(name, agent)  # unique name = stable namespace
        .add_edge("__start__", name)
        .compile(checkpointer=True)
    )
```

### 7.4 Resuming Multi-Agent Workflows from Checkpoints

Yes, you can resume a multi-agent workflow from a checkpoint. The checkpoint captures the **entire graph state** including:
- Parent graph state
- Which node was executing (or interrupted)
- Subgraph states (if subgraphs are discoverable)

```python
config = {"configurable": {"thread_id": "my-thread"}}

# Run until interrupt or completion
result = graph.invoke({"messages": [user_msg]}, config)

# Later: resume from the checkpoint
result = graph.invoke(Command(resume=user_response), config)
```

### 7.5 Production Checkpointers

| Checkpointer | Use Case |
|--------------|----------|
| `InMemorySaver` | Development/testing only |
| `SqliteSaver` | Single-machine persistence |
| `PostgresSaver` | Production; supports multiple workers |
| `AsyncPostgresSaver` | Production async workloads |
| `CosmosDBSaver` | Azure deployments |

### 7.6 Graph Migrations with Checkpoints

LangGraph supports topology changes while maintaining checkpointer state:

- **Ended threads:** Can modify entire topology (add, remove, rename nodes)
- **Interrupted threads:** All changes except node renaming/removal allowed
- **State keys:** Full backward/forward compatibility for additions/removals
- **Key renames:** Existing thread state lost for renamed keys

---

## 8. Streaming Across Agents

### 8.1 Stream Modes

LangGraph supports five stream modes:

| Mode | Purpose | Output |
|------|---------|--------|
| `values` | Full state after each step | Complete state snapshot |
| `updates` | State delta after each step | Node name + changes only |
| `messages` | LLM token streaming | `(message_chunk, metadata)` tuples |
| `custom` | Custom data from nodes | Whatever you emit via `get_stream_writer()` |
| `debug` | Maximum information | Full execution trace |

### 8.2 Streaming from Subgraphs

Enable with `subgraphs=True`:

```python
for chunk in graph.stream(
    {"messages": [user_msg]},
    subgraphs=True,
    stream_mode="updates"
):
    print(chunk)
```

Outputs include a **namespace tuple** identifying the source:

```python
# Output format: (namespace, data)
# namespace is a tuple path like:
# ("parent_node:<task_id>", "child_node:<task_id>")
```

### 8.3 Multiple Stream Modes

Combine modes simultaneously:

```python
for mode, chunk in graph.stream(
    inputs,
    stream_mode=["updates", "custom"]
):
    if mode == "updates":
        print("State update:", chunk)
    elif mode == "custom":
        print("Custom data:", chunk)
```

### 8.4 Filtering by Agent/Node

**By node name (langgraph_node metadata):**
```python
async for msg, metadata in graph.astream(inputs, stream_mode="messages"):
    if metadata.get("langgraph_node") == "research_agent":
        print(msg.content, end="", flush=True)
```

**By tags:**
```python
# Attach tags during model init
model = ChatOpenAI(tags=["research"])

# Filter in stream
async for msg, metadata in graph.astream(inputs, stream_mode="messages"):
    if "research" in metadata.get("tags", []):
        print(msg.content)
```

### 8.5 Custom Data Streaming from Agents

Emit arbitrary data from within agent nodes:

```python
from langgraph.config import get_stream_writer

def research_agent(state: State):
    writer = get_stream_writer()
    writer({"status": "Starting research...", "agent": "research"})
    # ... do work ...
    writer({"status": "Found 5 relevant papers", "agent": "research"})
    return {"messages": [AIMessage(content="Research complete")]}
```

### 8.6 HITL Streaming Pattern

Detect interrupts while streaming:

```python
async for metadata, mode, chunk in graph.astream(
    initial_input,
    stream_mode=["messages", "updates"],
    subgraphs=True,
    config=config
):
    if mode == "messages":
        display_streaming_content(msg.content)
    elif mode == "updates":
        if "__interrupt__" in chunk:
            interrupt_info = chunk["__interrupt__"][0].value
            user_response = get_user_input(interrupt_info)
            initial_input = Command(resume=user_response)
            break
```

### 8.7 Known Limitations

When combining `stream_mode=["messages", "custom"]` with `subgraphs=True`, streaming may not work properly in some configurations (as of 2025). This is an active area of development.

---

## 9. Tool Access and Scoping

### 9.1 Per-Agent Tool Scoping

Each agent in a multi-agent system has its own set of tools:

```python
# Research agent -- only has search tools
research_agent = create_agent(
    model,
    tools=[web_search, arxiv_search, pdf_reader],
    system_prompt="You are a research assistant..."
)

# Calendar agent -- only has calendar tools
calendar_agent = create_agent(
    model,
    tools=[create_event, list_events, delete_event],
    system_prompt="You are a calendar assistant..."
)

# Supervisor -- has agent-tools (no direct API access)
supervisor = create_agent(
    model,
    tools=[do_research, manage_calendar],
    system_prompt="You delegate to specialists..."
)
```

**Key principle:** Tools are partitioned across workers, each with focused prompts. The supervisor sees high-level tools and makes domain-level routing decisions, not individual API-level decisions.

### 9.2 ToolNode Security

`ToolNode` is the prebuilt node that executes tool calls:

- **Scoping:** ToolNode only exposes the tools you bind; models cannot call arbitrary tools
- **Isolation:** Each agent's ToolNode has its own tool registry
- **Error handling:** Tool errors are caught and returned as `ToolMessage` with error content
- **State injection:** Tools can receive state and store via `InjectedState` and `InjectedStore`

```python
from langgraph.prebuilt import ToolNode

# Each agent has its own ToolNode with its own tools
research_tools_node = ToolNode([web_search, arxiv_search])
calendar_tools_node = ToolNode([create_event, delete_event])
```

### 9.3 Dynamic Tool Binding

Tools can be dynamically resolved at runtime using callable models:

```python
def get_model_with_tools(state: State):
    """Dynamically bind tools based on state."""
    if state.get("current_step") == "research":
        return model.bind_tools([web_search, arxiv_search])
    elif state.get("current_step") == "writing":
        return model.bind_tools([write_document, edit_document])
    return model.bind_tools([])
```

### 9.4 Handoff Tools as Agent Access Control

In swarm and supervisor patterns, handoff tools define which agents can transfer to which other agents:

```python
# Alice can hand off to Bob and Carol, but not Dave
alice = create_agent(
    model,
    tools=[
        tool_a, tool_b,
        create_handoff_tool("Bob"),
        create_handoff_tool("Carol"),
    ],
    name="Alice"
)

# Bob can hand off to Alice only
bob = create_agent(
    model,
    tools=[
        tool_c,
        create_handoff_tool("Alice"),
    ],
    name="Bob"
)
```

This creates an **implicit access control graph** -- agents can only reach other agents they have handoff tools for.

---

## 10. Concurrency and Parallelism

### 10.1 Super-Steps and Automatic Parallelism

When a node has multiple outgoing edges, all destination nodes execute in parallel within the same super-step:

```python
# node_a fans out to node_b and node_c (parallel execution)
builder.add_edge("node_a", "node_b")
builder.add_edge("node_a", "node_c")
# node_b and node_c execute concurrently
```

### 10.2 The `Send()` API -- Dynamic Fan-Out

`Send()` enables **dynamic** routing with variable numbers of node instances and custom state per instance:

```python
from langgraph.types import Send

def continue_to_jokes(state: OverallState):
    """Dynamically create parallel joke-generation tasks."""
    return [
        Send("generate_joke", {"subject": s})
        for s in state["subjects"]  # Variable number of tasks
    ]

builder.add_conditional_edges("collect_subjects", continue_to_jokes)
```

**Key capabilities:**
- Number of parallel tasks determined at runtime (not compile time)
- Each `Send()` receives its own custom state
- Results merge via reducers (e.g., `Annotated[list[str], add]`)

### 10.3 Map-Reduce Pattern

The canonical map-reduce pattern using `Send()`:

```python
from typing import Annotated, TypedDict
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

class OverallState(TypedDict):
    subjects: list[str]
    jokes: Annotated[list[str], add]  # Reducer: append results

class JokeState(TypedDict):
    subject: str

def generate_topics(state: OverallState):
    return {"subjects": ["cats", "dogs", "birds"]}

def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

def generate_joke(state: JokeState):
    joke = llm.invoke(f"Tell me a joke about {state['subject']}")
    return {"jokes": [joke.content]}

def collect_jokes(state: OverallState):
    return {"jokes": state["jokes"]}

builder = StateGraph(OverallState)
builder.add_node("generate_topics", generate_topics)
builder.add_node("generate_joke", generate_joke)
builder.add_node("collect_jokes", collect_jokes)
builder.add_edge(START, "generate_topics")
builder.add_conditional_edges("generate_topics", continue_to_jokes)
builder.add_edge("generate_joke", "collect_jokes")
builder.add_edge("collect_jokes", END)
graph = builder.compile()
```

### 10.4 Concurrency Control

```python
# Limit parallel execution
result = graph.invoke(
    inputs,
    config={"max_concurrency": 3}  # Max 3 concurrent tasks
)
```

### 10.5 Error Handling in Parallel Execution

**Atomic super-step failure:** If one parallel node fails, the **entire super-step fails atomically**. If one node succeeds and another fails, neither result gets saved to state. This requires robust retry logic or fallback strategies in node design.

### 10.6 The Defer Pattern

LangGraph's defer pattern solves coordination of parallel branches with **asymmetric completion times**:

- Creates explicit synchronization barriers
- Ensures agent nodes always operate on complete information
- Prevents race conditions in map-reduce workflows

---

## 11. Memory and Persistence

### 11.1 Short-Term Memory (Thread-Scoped)

Managed within agent state via checkpoints:

- Conversation history maintained per thread
- Accessible only within a single conversational session
- Updated when graph invoked or steps completed
- Stored in checkpointer (SQLite, Postgres, etc.)

### 11.2 Long-Term Memory (Cross-Thread via Store)

The `Store` abstraction provides namespaced, persistent memory across threads and agents:

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore(
    index={"embed": embed_function, "dims": 768}  # For semantic search
)

graph = builder.compile(checkpointer=checkpointer, store=store)
```

### 11.3 Store Operations

```python
# Write
store.put(
    namespace=("user-123", "preferences"),
    key="language",
    value={"language": "English", "style": "concise"}
)

# Read
item = store.get(("user-123", "preferences"), "language")

# Search (semantic + filter)
items = store.search(
    namespace=("user-123", "preferences"),
    filter={"language": "English"},
    query="communication preferences"  # Semantic search
)
```

### 11.4 Namespaced Memory Architecture

Memories are organized hierarchically using **namespace tuples**:

```
("user-123", "chitchat")     -- User's casual conversation memory
("user-123", "preferences")  -- User's preferences
("org-456", "policies")      -- Organization-wide policies
("agent-research", "cache")  -- Agent-specific cache
```

### 11.5 Memory Types

| Type | Storage | Use Case | Pattern |
|------|---------|----------|---------|
| **Semantic** | Facts/concepts | User profiles, entity knowledge | Profile or Collection |
| **Episodic** | Past experiences | Few-shot examples | Store or LangSmith Datasets |
| **Procedural** | Rules/instructions | System prompts, agent behavior | Reflection/meta-prompting |

### 11.6 Shared vs Per-Agent Memory

**Shared memory:** Different agents accessing the same namespace tuple can retrieve shared memories:

```python
def agent_a_node(state, store):
    # Both agents read/write to the same namespace
    shared_data = store.search(("project-123", "findings"))
    return {"messages": [...]}

def agent_b_node(state, store):
    # Same namespace -- sees agent_a's writes
    shared_data = store.search(("project-123", "findings"))
    return {"messages": [...]}
```

**Per-agent memory:** Use agent-specific namespaces for isolation:

```python
def research_agent(state, store):
    # Agent-specific namespace
    my_cache = store.search(("agent", "research", "cache"))
    store.put(("agent", "research", "cache"), "result_1", {"data": "..."})
    return {"messages": [...]}

def writing_agent(state, store):
    # Different namespace -- isolated from research agent
    my_drafts = store.search(("agent", "writing", "drafts"))
    return {"messages": [...]}
```

### 11.7 Accessing Store in Nodes

```python
from langgraph.store.base import BaseStore

def my_node(state: State, store: BaseStore):
    """Store is automatically injected when graph is compiled with store=..."""
    namespace = ("user", state.get("user_id", "default"))
    memories = store.search(namespace)

    # Use memories in prompt
    prompt = f"User preferences: {memories}\n\nRespond to: {state['messages'][-1]}"
    response = llm.invoke(prompt)

    # Save new memory
    store.put(namespace, "last_interaction", {
        "topic": "scheduling",
        "timestamp": datetime.now().isoformat()
    })

    return {"messages": [response]}
```

### 11.8 Memory Writing Patterns

**Hot path (synchronous):** Real-time updates during user interaction. Immediate availability but increased latency.

**Background (asynchronous):** Separate scheduled task. No latency impact but delayed availability across threads.

### 11.9 Self-Improving Agents (Procedural Memory)

Agents can modify their own instructions through reflection:

```python
def update_instructions(state: State, store: BaseStore):
    namespace = ("agent_instructions",)
    current = store.search(namespace)[0]
    new_instructions = llm.invoke(
        f"Current instructions: {current}\n"
        f"Feedback: {state['messages']}\n"
        f"Generate improved instructions."
    )
    store.put(namespace, "agent_a", {"instructions": new_instructions.content})
```

---

## 12. Prebuilt Components

### 12.1 Package: `langgraph-prebuilt`

Core prebuilt utilities in the `langgraph.prebuilt` module:

#### `create_react_agent`

Factory function creating a ReAct (Reasoning + Acting) agent graph:

```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    model=model,                     # Language model or callable
    tools=[tool_a, tool_b],          # List of tools or ToolNode
    prompt="You are a helpful...",   # String, SystemMessage, callable, or Runnable
    state_schema=CustomState,        # Optional custom state TypedDict
    response_format=AnswerSchema,    # Optional Pydantic model for structured output
    pre_model_hook=trim_messages,    # Optional: runs before every LLM call
    post_model_hook=validate_output, # Optional: runs after every LLM call (v2)
    name="research_agent",           # Agent name (for multi-agent identification)
    interrupt_before=["tools"],      # Pause points for HITL
    interrupt_after=None,
    checkpointer=checkpointer,       # State persistence
    store=store,                     # Long-term memory
)
```

**Internal graph structure:**

```
START -> [pre_model_hook?] -> [agent (call_model)] -> should_continue?
                ^                                          |
                |                                    tool_calls?
                |                                   /          \
                |                                yes            no
                |                                 |              |
        [tools (ToolNode)] <--[post_model_hook?]-'     -> [structured_response?] -> END
```

**Default state schema:**

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    remaining_steps: RemainingSteps  # Auto-tracked step counter
    structured_response: StructuredResponse  # When response_format is set
```

**`pre_model_hook` contract:**
- Input: State dict
- Output: Dict with `messages` and/or `llm_input_messages`
- If `llm_input_messages` present: used for LLM input only (state unchanged)
- If only `messages`: updates state AND used for LLM input
- Use case: Trimming long message histories, injecting context

**`post_model_hook` contract (v2):**
- Runs after LLM invocation
- Can implement validation, human-in-the-loop checks
- Routes to: tools (if pending tool calls), structured_response (if format specified), or END

#### `ToolNode`

Prebuilt node for executing tool calls:

```python
from langgraph.prebuilt import ToolNode

tools_node = ToolNode(
    tools=[web_search, calculator],
    # Handles parallel tool execution, errors, state injection
)
```

**Features:**
- Parallel tool execution within a single step
- Error handling with configurable strategies
- State injection via `InjectedState`
- Store injection via `InjectedStore`
- Tool call validation

#### `tools_condition`

Prebuilt conditional edge function:

```python
from langgraph.prebuilt import tools_condition

builder.add_conditional_edges("agent", tools_condition)
# Routes to "tools" if last message has tool_calls, else END
```

### 12.2 Package: `langgraph-supervisor`

```bash
pip install langgraph-supervisor
```

```python
from langgraph_supervisor import create_supervisor, create_handoff_tool

# create_supervisor signature
workflow = create_supervisor(
    agents=[agent_a, agent_b],
    model=model,
    prompt="You coordinate agents...",
    supervisor_name="supervisor",
    tools=[],
    output_mode="full_history",  # or "last_message"
    handoff_tool_prefix="transfer_to",
    add_handoff_messages=True
)
app = workflow.compile(checkpointer=checkpointer)

# create_handoff_tool signature
handoff = create_handoff_tool(
    agent_name="research_agent",
    name="transfer_to_research",         # Optional custom tool name
    description="Hand off to research"   # Optional custom description
)
```

### 12.3 Package: `langgraph-swarm`

```bash
pip install langgraph-swarm
```

```python
from langgraph_swarm import create_swarm, create_handoff_tool

# Create agents with handoff tools
alice = create_agent(
    model,
    tools=[tool_a, create_handoff_tool("Bob")],
    system_prompt="You handle travel planning.",
    name="Alice"
)
bob = create_agent(
    model,
    tools=[tool_b, create_handoff_tool("Alice")],
    system_prompt="You handle bookings.",
    name="Bob"
)

# Create and compile swarm
workflow = create_swarm(
    [alice, bob],
    default_active_agent="Alice"
)
app = workflow.compile(checkpointer=checkpointer)
```

**Swarm state schema:**
```python
class SwarmState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    active_agent: str
```

### 12.4 Other Prebuilt Libraries

| Library | Purpose |
|---------|---------|
| **Trustcall** | Reliable structured data extraction |
| **LangMem** | Long-term memory management |
| **langgraph-checkpoint-sqlite** | SQLite checkpointer |
| **langgraph-checkpoint-postgres** | PostgreSQL checkpointer |

---

## 13. Comparison: LangGraph vs OpenAI Handoffs

### 13.1 OpenAI Swarm / Agents SDK Approach

OpenAI's original Swarm (now deprecated, replaced by Agents SDK) introduced the handoff concept:

- **Stateless client-side design** -- no built-in persistence
- Handoffs via functions that **return the next Agent object**
- Typically 3-4 agents: triage agent + specialist agents
- Minimal framework overhead, easy mental model
- No built-in checkpointing, streaming, or human-in-the-loop

**OpenAI Agents SDK** (successor):
- Production-ready evolution keeping same core mental model (agents, handoffs)
- Adds guardrails, sessions for conversation history, built-in tracing
- Now provider-agnostic (supports 100+ LLMs)

### 13.2 LangGraph Approach

- **Stateful graph-based design** with built-in persistence
- Handoffs via `Command` objects with explicit state updates
- Supports arbitrary numbers of agents in complex topologies
- Built-in checkpointing, streaming, human-in-the-loop, memory
- Higher learning curve but more powerful

### 13.3 Key Differences

| Feature | OpenAI Agents SDK | LangGraph |
|---------|------------------|-----------|
| **State management** | Sessions (basic) | Typed state schemas with reducers, checkpointers |
| **Handoff mechanism** | Function returns Agent | `Command` with state updates + routing |
| **Persistence** | Sessions | Full checkpointing (SQLite, Postgres, etc.) |
| **Human-in-the-loop** | Not built-in | `interrupt()`, breakpoints, middleware |
| **Streaming** | Basic | 5 stream modes, subgraph streaming, filtering |
| **Concurrency** | Manual | `Send()` API, automatic fan-out, map-reduce |
| **Memory** | Not built-in | `Store` with namespaces, semantic search |
| **Observability** | Built-in tracing | LangSmith integration |
| **Graph visualization** | No | Yes (Mermaid, LangGraph Studio) |
| **Learning curve** | Low | Medium-High |

### 13.4 Recommendation

> Prototype with Swarm patterns using the mental model of "handoffs" to define business domains (clarity is useful for product definition), while building core logic in LangGraph for production scenarios requiring reliability, state management, and observability.

---

## 14. Key Takeaways for Our Design

### 14.1 Architecture Insights

1. **Agents-as-tools is the recommended supervisor pattern.** Sub-agents wrapped as tools give the supervisor clear, high-level routing decisions while keeping each agent focused on its domain.

2. **Command is the universal control primitive.** It combines state updates and routing in a single return value, enabling handoffs, cross-graph navigation (via `Command.PARENT`), and dynamic routing.

3. **State schema boundaries are the primary isolation mechanism.** Different schemas between parent and child force explicit transformation, preventing state leaks.

4. **Reducers are essential for concurrent writes.** When multiple agents write to the same state key, reducers (e.g., `add` for lists, `add_messages` for messages) ensure correct merging.

### 14.2 Multi-Agent Patterns Worth Studying

1. **Supervisor with agents-as-tools** -- simplest, most recommended
2. **Swarm with handoff tools** -- for peer-to-peer agent collaboration
3. **Hierarchical with nested supervisors** -- for complex organizations
4. **Map-reduce with `Send()`** -- for parallel processing tasks

### 14.3 Key Primitives to Consider

| Primitive | Purpose | Our Equivalent? |
|-----------|---------|-----------------|
| `StateGraph` | Define agent graph | Agent loop graph |
| `Command` | State update + routing | Yield-based control flow |
| `Send()` | Dynamic fan-out | Parallel agent dispatch |
| `interrupt()` | Human-in-the-loop pause | Input request mechanism |
| `Store` | Long-term namespaced memory | Persistent memory store |
| `ToolNode` | Tool execution with scoping | Tool runner |
| `create_react_agent` | Pre-built ReAct agent | Agent factory |
| `create_handoff_tool` | Agent-to-agent transfer | Handoff mechanism |

### 14.4 Design Considerations

- **Checkpointing is mandatory** for any production multi-agent system (enables resume, HITL, debugging)
- **Namespace isolation** prevents checkpoint conflicts between parallel agents
- **Super-step atomic failure** means error handling must be per-node, with retry logic
- **Node restart on resume** means code before `interrupt()` must be idempotent
- **Streaming with subgraphs** requires `subgraphs=True` and careful namespace filtering
- **Message history management** is a critical performance concern -- full history handoffs become expensive at scale

---

## Sources

- [LangGraph Official Documentation](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph GitHub Repository](https://github.com/langchain-ai/langgraph)
- [langgraph-supervisor-py GitHub](https://github.com/langchain-ai/langgraph-supervisor-py)
- [langgraph-swarm-py GitHub](https://github.com/langchain-ai/langgraph-swarm-py)
- [LangGraph Multi-Agent Workflows Blog](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- [Command: A New Tool for Multi-Agent Architectures Blog](https://blog.langchain.com/command-a-new-tool-for-multi-agent-architectures-in-langgraph/)
- [LangGraph 0.3 Release: Prebuilt Agents Blog](https://www.blog.langchain.com/langgraph-0-3-release-prebuilt-agents/)
- [LangGraph Supervisor Announcement](https://changelog.langchain.com/announcements/langgraph-supervisor-a-library-for-hierarchical-multi-agent-systems)
- [Benchmarking Multi-Agent Architectures Blog](https://blog.langchain.com/benchmarking-multi-agent-architectures/)
- [Making it Easier to Build HITL Agents with interrupt Blog](https://blog.langchain.com/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt/)
- [LangGraph Subgraphs Documentation](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangGraph Interrupts Documentation](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Memory Documentation](https://docs.langchain.com/oss/python/langgraph/memory)
- [LangGraph Streaming Documentation](https://docs.langchain.com/oss/python/langgraph/streaming)
- [Handoffs Documentation](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)
- [Supervisor Pattern Documentation](https://docs.langchain.com/oss/python/langchain/supervisor)
- [Workflows and Agents Documentation](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [ReAct Agent DeepWiki](https://deepwiki.com/langchain-ai/langgraph/8.1-react-agent-(create_react_agent))
- [Hierarchical Agent Teams Tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/)
- [How Agent Handoffs Work - Towards Data Science](https://towardsdatascience.com/how-agent-handoffs-work-in-multi-agent-systems/)
- [Scaling LangGraph Agents - AI Practitioner](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization)
