# OpenAI Agents SDK: Sub-Agents & Multi-Agent Patterns -- Deep Research

> **Date:** 2026-02-26
> **Subject:** Comprehensive deep-dive into how the OpenAI Agents SDK handles sub-agents, handoffs, and multi-agent orchestration
> **Repo:** [openai/openai-agents-python](https://github.com/openai/openai-agents-python)
> **Docs:** [openai.github.io/openai-agents-python](https://openai.github.io/openai-agents-python/)
> **SDK Version Context:** Latest as of Feb 2026 (evolved from OpenAI Swarm)

---

## Table of Contents

1. [Multi-Agent Architecture Overview](#1-multi-agent-architecture-overview)
2. [Handoff Mechanism](#2-handoff-mechanism)
3. [Agent Definition for Multi-Agent Use](#3-agent-definition-for-multi-agent-use)
4. [Context and State Across Agent Boundaries](#4-context-and-state-across-agent-boundaries)
5. [Nesting, Chaining, and Circular Handoff Handling](#5-nesting-chaining-and-circular-handoff-handling)
6. [Tool Access and Scoping](#6-tool-access-and-scoping)
7. [Guardrails Across Agent Boundaries](#7-guardrails-across-agent-boundaries)
8. [Runner and Multi-Agent Execution](#8-runner-and-multi-agent-execution)
9. [Tracing Across Agent Handoffs](#9-tracing-across-agent-handoffs)
10. [MCP Integration in Multi-Agent Setups](#10-mcp-integration-in-multi-agent-setups)
11. [Concurrency and Parallel Execution](#11-concurrency-and-parallel-execution)
12. [Example Patterns from the SDK Repository](#12-example-patterns-from-the-sdk-repository)
13. [Summary Comparison: Handoffs vs. Agents-as-Tools](#13-summary-comparison-handoffs-vs-agents-as-tools)
14. [Sources](#14-sources)

---

## 1. Multi-Agent Architecture Overview

The OpenAI Agents SDK supports two fundamentally different multi-agent orchestration patterns, plus a code-level orchestration approach for maximum control.

### Pattern 1: Handoffs (Decentralized Peer Delegation)

Agents hand off **control of the conversation** to another agent. The target agent takes over completely, receiving the full message history. The originating agent relinquishes control.

```
User --> [Triage Agent] --handoff--> [Refund Agent] --handoff--> [Escalation Agent]
              |                            |                           |
              v                            v                           v
         Routes request            Handles refund              Escalates to human
```

**Key characteristics:**
- Target agent **takes over** the conversation
- Full conversation history is transferred (by default)
- Decentralized -- no single orchestrator
- Handoffs are represented as tool calls to the LLM (`transfer_to_<agent_name>`)

### Pattern 2: Agents as Tools (Centralized Manager/Orchestrator)

A central manager agent invokes specialized sub-agents as **tool calls**. The manager retains control throughout. Sub-agents run in isolation and return results to the manager.

```
User --> [Manager Agent]
              |
              +-- tool call --> [Spanish Agent] --> returns translation
              +-- tool call --> [Refund Agent]  --> returns refund status
              +-- tool call --> [Search Agent]  --> returns search results
              |
              v
         Manager synthesizes final response
```

**Key characteristics:**
- Manager **retains control** of the conversation
- Sub-agents see only the tool input, not the full history
- Centralized orchestration
- Sub-agents exposed via `agent.as_tool()`

### Pattern 3: Code-Level Orchestration

Developers chain agent runs explicitly using Python code, with full programmatic control over routing, data flow, and parallelism.

```python
# Sequential chaining
result1 = await Runner.run(classifier_agent, user_input)
category = result1.final_output.category

if category == "billing":
    result2 = await Runner.run(billing_agent, user_input)
elif category == "technical":
    result2 = await Runner.run(tech_agent, user_input)

# Parallel fan-out
results = await asyncio.gather(
    Runner.run(sentiment_agent, text),
    Runner.run(summary_agent, text),
    Runner.run(entity_agent, text),
)
final = await Runner.run(merge_agent, combine_outputs(results))
```

**Key characteristics:**
- Maximum determinism and predictability
- Full control over cost, speed, and routing logic
- Uses structured outputs for programmatic branching
- Can combine with `asyncio.gather` for parallel execution

---

## 2. Handoff Mechanism

### 2.1 How Handoffs Work Internally

Handoffs are **tool calls** from the LLM's perspective. When an agent has handoffs configured, each target agent is registered as a callable tool.

**Step-by-step flow:**

1. The `Agent.handoffs` list is converted to tool definitions at the start of the run
2. Each handoff becomes a tool named `transfer_to_<agent_name>` (customizable)
3. The LLM can choose to call this tool like any other tool
4. When the Runner detects a handoff tool call, it:
   a. Executes the `on_handoff` callback (if defined)
   b. Applies any `input_filter` to the conversation history
   c. Switches the current agent to the target agent
   d. Passes the (possibly filtered) conversation history to the new agent
   e. Continues the agent loop from the new agent

### 2.2 The `Handoff` Class (Full API)

```python
@dataclass
class Handoff(Generic[TContext, TAgent]):
    tool_name: str                    # Name of the tool (default: transfer_to_<agent_name>)
    tool_description: str             # Description visible to the LLM
    input_json_schema: dict[str, Any] # JSON schema for handoff inputs (empty if no input)
    on_invoke_handoff: Callable[      # Function called when handoff fires
        [RunContextWrapper[Any], str],
        Awaitable[TAgent]
    ]
    agent_name: str                   # Name of the target agent
    input_filter: HandoffInputFilter | None  # Filter for conversation history
    nest_handoff_history: bool | None        # Override run-level nesting for this handoff
    strict_json_schema: bool = True          # Enforce strict JSON schema (recommended)
    is_enabled: bool | Callable[             # Runtime enable/disable
        [RunContextWrapper[Any], Agent[TContext]],
        MaybeAwaitable[bool]
    ] = True
```

### 2.3 The `handoff()` Factory Function (Full Signature)

The `handoff()` function is the primary way to create customized handoffs:

```python
def handoff(
    agent: Agent[TContext],
    tool_name_override: str | None = None,
    tool_description_override: str | None = None,
    on_handoff: OnHandoffWithInput[THandoffInput] | OnHandoffWithoutInput | None = None,
    input_type: type[THandoffInput] | None = None,
    input_filter: Callable[[HandoffInputData], HandoffInputData] | None = None,
    nest_handoff_history: bool | None = None,
    is_enabled: bool | Callable[
        [RunContextWrapper[Any], Agent[TContext]],
        MaybeAwaitable[bool]
    ] = True,
) -> Handoff[TContext, Agent[TContext]]
```

**Parameters in detail:**

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `agent` | `Agent[TContext]` | Required | The target agent to hand off to |
| `tool_name_override` | `str \| None` | `None` | Custom tool name (default: `transfer_to_<agent.name>`) |
| `tool_description_override` | `str \| None` | `None` | Custom tool description for the LLM |
| `on_handoff` | Callback | `None` | Async function called when handoff fires |
| `input_type` | `type[BaseModel]` | `None` | Pydantic model for LLM-provided handoff data |
| `input_filter` | `Callable` | `None` | Filters/transforms conversation history before passing to target |
| `nest_handoff_history` | `bool \| None` | `None` | Override run-level `nest_handoff_history` setting |
| `is_enabled` | `bool \| Callable` | `True` | Runtime enable/disable (disabled handoffs are hidden from LLM) |

### 2.4 Basic Handoff (Agent Reference in `handoffs` List)

The simplest form -- just put Agent objects in the `handoffs` list:

```python
booking_agent = Agent(
    name="Booking agent",
    instructions="You handle booking requests.",
    handoff_description="Transfer to this agent for booking-related questions",
)

refund_agent = Agent(
    name="Refund agent",
    instructions="You handle refund requests.",
    handoff_description="Transfer to this agent for refund-related questions",
)

triage_agent = Agent(
    name="Triage agent",
    instructions="Route the user to the appropriate specialist.",
    handoffs=[booking_agent, refund_agent],
)

result = await Runner.run(triage_agent, "I need a refund for my last order")
# triage_agent calls transfer_to_refund_agent --> refund_agent takes over
```

The `handoff_description` field on the target agent provides a hint to the LLM about when to trigger the handoff. This becomes part of the tool description.

### 2.5 Customized Handoff with `handoff()`

```python
from agents import handoff, Agent, RunContextWrapper
from pydantic import BaseModel

class EscalationData(BaseModel):
    reason: str
    severity: str  # "low", "medium", "high"

async def on_escalation(ctx: RunContextWrapper[None], input_data: EscalationData):
    """Called when the handoff is invoked. Good for data fetching or logging."""
    print(f"Escalation triggered: {input_data.reason} (severity: {input_data.severity})")
    await log_escalation(ctx.context, input_data)

escalation_handoff = handoff(
    agent=escalation_agent,
    tool_name_override="escalate_to_supervisor",
    tool_description_override="Escalate to a human supervisor when the user is upset or the issue is critical",
    on_handoff=on_escalation,
    input_type=EscalationData,  # LLM will provide structured data when calling the handoff
)

frontline_agent = Agent(
    name="Frontline agent",
    instructions="Handle customer requests. Escalate if needed.",
    handoffs=[escalation_handoff],
)
```

### 2.6 `on_handoff` Callback Signatures

There are two overloads depending on whether `input_type` is provided:

```python
# Without input_type -- callback receives only context
async def on_handoff_simple(ctx: RunContextWrapper[TContext]) -> None:
    ...

# With input_type -- callback also receives parsed LLM input
async def on_handoff_with_input(
    ctx: RunContextWrapper[TContext],
    input_data: THandoffInput,    # Pydantic model instance
) -> None:
    ...
```

The `on_handoff` callback is useful for:
- Kicking off async data fetching before the target agent starts
- Logging handoff events
- Mutating shared context with handoff-specific data
- Validating the handoff request

### 2.7 Dynamic Handoff Enable/Disable

Handoffs can be conditionally enabled at runtime:

```python
escalation_handoff = handoff(
    agent=escalation_agent,
    is_enabled=lambda ctx, agent: ctx.context.user_tier == "premium",
    # Only premium users can escalate
)

# Or with an async function for complex logic
async def check_escalation_eligible(ctx: RunContextWrapper[AppContext], agent: Agent) -> bool:
    rate = await get_escalation_rate(ctx.context.user_id)
    return rate < 5  # Max 5 escalations per day

escalation_handoff = handoff(
    agent=escalation_agent,
    is_enabled=check_escalation_eligible,
)
```

When `is_enabled` returns `False`, the handoff tool is **completely hidden** from the LLM -- it will not appear in the tool list.

---

## 3. Agent Definition for Multi-Agent Use

### 3.1 Agent Class Fields Relevant to Multi-Agent

```python
@dataclass
class Agent(Generic[TContext]):
    name: str                                   # Required. Unique identifier.
    instructions: str | Callable | None = None  # System prompt (static or dynamic)
    handoffs: list[Agent | Handoff] = []        # Peer agents for delegation
    handoff_description: str | None = None      # Description when THIS agent is a handoff target
    tools: list[Tool] = []                      # Tools scoped to this agent
    mcp_servers: list[MCPServer] = []           # MCP servers scoped to this agent
    mcp_config: MCPConfig = {}                  # MCP configuration
    model: str | Model | None = None            # LLM model (can differ per agent)
    model_settings: ModelSettings = ...         # Model tuning parameters
    output_type: type | None = None             # Pydantic model for structured output
    input_guardrails: list[InputGuardrail] = [] # Input validation
    output_guardrails: list[OutputGuardrail] = [] # Output validation
    hooks: AgentHooks | None = None             # Per-agent lifecycle callbacks
    tool_use_behavior: ... = "run_llm_again"    # How tool results are handled
    reset_tool_choice: bool = True              # Prevent infinite tool loops
    prompt: Prompt | DynamicPromptFunction | None = None  # Prompt template reference
```

### 3.2 `as_tool()` Method (Full Signature)

Converts an agent into a callable tool for the manager/orchestrator pattern:

```python
def as_tool(
    self,
    tool_name: str,
    tool_description: str,
    *,
    custom_output_extractor: Callable | None = None,
    is_enabled: bool | Callable = True,
    on_stream: Callable[[AgentToolStreamEvent], Awaitable[None]] | None = None,
    failure_error_function: Callable | None = ...,
    parameters: type | None = None,        # Pydantic model or dataclass for structured input
    input_builder: Callable | None = None, # Custom argument-to-input mapping
    needs_approval: bool | Callable = False,
    max_turns: int | None = None,          # Limit turns for the sub-agent run
    run_config: RunConfig | None = None,   # Config for the sub-agent run
    hooks: RunHooks | None = None,         # Hooks for the sub-agent run
    include_input_schema: bool = False,    # Include full JSON schema in nested input
) -> FunctionTool
```

**Key parameters for multi-agent control:**

- **`parameters`**: Define a Pydantic model or dataclass that the orchestrator's LLM populates when calling this tool. Provides structured input to the sub-agent.
- **`custom_output_extractor`**: Transform the sub-agent's `RunResult` into a different output before returning to the orchestrator.
- **`max_turns`**: Constrain how many turns the sub-agent can take (prevents runaway sub-agents).
- **`needs_approval`**: Add human-in-the-loop gating before the sub-agent runs.
- **`on_stream`**: Receive `AgentToolStreamEvent` objects from the nested agent's streaming output.
- **`is_enabled`**: Conditionally show/hide this tool from the orchestrator's LLM.

### 3.3 `clone()` Method

Create agent variants efficiently:

```python
base_agent = Agent(
    name="Base",
    instructions="You are a helpful assistant.",
    tools=[get_weather, search],
)

# Create a variant with different instructions but same tools
specialized_agent = base_agent.clone(
    name="Specialist",
    instructions="You specialize in weather forecasting.",
)
```

`clone()` performs a shallow copy. Mutable attributes (like `tools` list) share references unless explicitly replaced.

---

## 4. Context and State Across Agent Boundaries

### 4.1 RunContext / RunContextWrapper

Context is the **local state and dependency injection** mechanism. It is **never sent to the LLM** -- purely local.

```python
@dataclass
class AppContext:
    user_id: str
    db: DatabasePool
    escalation_count: int = 0

# All agents in a single run share the SAME context instance
result = await Runner.run(
    triage_agent,    # May hand off to refund_agent, then escalation_agent
    "I need help",
    context=AppContext(user_id="u_123", db=pool),
)
```

**Critical rule:** Every agent, tool, hook, and guardrail in a single `Runner.run()` invocation must use the **same context type** (`TContext`). This is enforced by the type system -- `Agent[AppContext]` will only accept tools and hooks typed with `AppContext`.

### 4.2 Context During Handoffs

When a handoff occurs:
- The **same `RunContextWrapper` instance** continues to be used
- The target agent, its tools, and its hooks all receive the same context object
- Tools in the target agent can read and write to context that was modified by the originating agent's tools

```python
@function_tool
async def log_user_issue(ctx: RunContextWrapper[AppContext], issue: str) -> str:
    ctx.context.escalation_count += 1  # Mutate shared context
    return "Issue logged"

# If triage_agent runs log_user_issue, then hands off to refund_agent,
# refund_agent's tools will see escalation_count == 1
```

### 4.3 Conversation History During Handoffs

By default, the **entire conversation history** (all messages from all prior agents) is passed to the target agent. This includes:
- The original user input
- All LLM responses from prior agents
- All tool call/result messages
- The handoff tool call itself

This can be controlled via:

#### Input Filters (per-handoff)

```python
def my_filter(data: HandoffInputData) -> HandoffInputData:
    """Filter what the target agent sees."""
    return data.clone(
        input_history=data.input_history[-5:],  # Only last 5 history items
        pre_handoff_items=(),                    # Clear pre-handoff items
    )

custom_handoff = handoff(agent=target_agent, input_filter=my_filter)
```

#### `HandoffInputData` Structure

```python
@dataclass
class HandoffInputData:
    input_history: str | tuple[TResponseInputItem, ...]  # Pre-run conversation history
    pre_handoff_items: tuple[RunItem, ...]                # Items before handoff invocation
    new_items: tuple[RunItem, ...]                        # Items including handoff trigger
    run_context: RunContextWrapper[Any] | None = None     # Context at handoff time
    input_items: tuple[RunItem, ...] | None = None        # Filtered items for next agent

    def clone(**kwargs) -> HandoffInputData: ...          # Create modified copy
```

#### Built-in Filters (`agents.extensions.handoff_filters`)

```python
from agents.extensions.handoff_filters import remove_all_tools, nest_handoff_history

# Remove all tool call/result messages from history
clean_handoff = handoff(agent=target_agent, input_filter=remove_all_tools)

# Collapse prior transcript into a summarized assistant message
summarized_handoff = handoff(
    agent=target_agent,
    input_filter=lambda data: nest_handoff_history(data),
)
```

**`remove_all_tools(data: HandoffInputData) -> HandoffInputData`**
Strips all tool-related items (function calls, function outputs, file search, web search) from the history.

**`nest_handoff_history(data: HandoffInputData, *, history_mapper=None) -> HandoffInputData`**
Collapses the prior transcript into a single assistant message wrapped in `<CONVERSATION HISTORY>` markers. Accepts an optional `history_mapper` callable for custom summarization.

**`default_handoff_history_mapper(transcript) -> list[TResponseInputItem]`**
Returns a single assistant message summarizing the transcript.

#### Global Handoff Configuration via `RunConfig`

```python
from agents import RunConfig

run_config = RunConfig(
    # Apply a global input filter to ALL handoffs that don't have their own
    handoff_input_filter=remove_all_tools,

    # Enable nested history collapsing for ALL handoffs
    nest_handoff_history=True,

    # Custom history mapping function
    handoff_history_mapper=my_custom_mapper,
)

result = await Runner.run(triage_agent, "Help me", run_config=run_config)
```

Priority order for handoff history handling:
1. Per-handoff `input_filter` (highest priority)
2. Per-handoff `nest_handoff_history` override
3. `RunConfig.handoff_input_filter`
4. `RunConfig.nest_handoff_history` + `RunConfig.handoff_history_mapper`
5. Default: pass full raw history (lowest priority)

#### Customizing History Wrappers

```python
from agents.extensions.handoff_filters import (
    set_conversation_history_wrappers,
    get_conversation_history_wrappers,
    reset_conversation_history_wrappers,
)

# Change the markers used when nesting history
set_conversation_history_wrappers("<PRIOR_CHAT>", "</PRIOR_CHAT>")

# Check current markers
start, end = get_conversation_history_wrappers()  # ("<PRIOR_CHAT>", "</PRIOR_CHAT>")

# Reset to defaults
reset_conversation_history_wrappers()  # Back to "<CONVERSATION HISTORY>"
```

### 4.4 Conversation History with Agents-as-Tools

When using the `as_tool()` pattern, the sub-agent does **NOT** receive the full conversation history. It receives only:
- The tool input string (what the orchestrator's LLM passed as the tool argument)
- Or structured input if `parameters` is specified on `as_tool()`

This is a fundamental difference from handoffs. The sub-agent runs in isolation from the parent conversation.

### 4.5 Handoff Prompt Helpers

The SDK provides utilities for crafting instructions that guide the LLM on handoff behavior:

```python
from agents.extensions.handoff_prompt import (
    RECOMMENDED_PROMPT_PREFIX,
    prompt_with_handoff_instructions,
)

triage_agent = Agent(
    name="Triage",
    instructions=prompt_with_handoff_instructions(
        "You are a customer support triage agent. Route users to the appropriate specialist."
    ),
    handoffs=[booking_agent, refund_agent],
)
```

`RECOMMENDED_PROMPT_PREFIX` contains guidance text that helps the LLM understand how and when to use handoffs effectively.

---

## 5. Nesting, Chaining, and Circular Handoff Handling

### 5.1 Can Handoff Targets Hand Off to Further Agents?

**Yes.** There is no inherent limit on handoff depth. A target agent can itself have handoffs, creating chains:

```python
level1_agent = Agent(
    name="Level 1",
    instructions="You are a frontline agent. Escalate complex issues.",
    handoffs=[level2_agent],
)

level2_agent = Agent(
    name="Level 2",
    instructions="You handle complex issues. Escalate critical ones.",
    handoffs=[level3_agent],
)

level3_agent = Agent(
    name="Level 3",
    instructions="You handle critical issues directly.",
)

# Execution: Level 1 -> Level 2 -> Level 3
result = await Runner.run(level1_agent, "I have a critical billing issue")
```

### 5.2 Circular Handoffs

Agents **can** hand off back to each other, creating cycles:

```python
agent_a = Agent(name="Agent A", handoffs=[])
agent_b = Agent(name="Agent B", handoffs=[agent_a])
agent_a.handoffs = [agent_b]  # Circular reference

# A -> B -> A -> B -> ... until max_turns
```

The SDK does **not** explicitly detect or prevent circular handoffs at configuration time. Instead, it relies on the **`max_turns` parameter** as the termination mechanism.

### 5.3 `max_turns` as the Depth/Loop Guard

```python
result = await Runner.run(
    triage_agent,
    "Help me",
    max_turns=10,  # Default is DEFAULT_MAX_TURNS (10)
)
```

**How `max_turns` works:**
- Each iteration of the agent loop (LLM call + tool execution or handoff) counts as one turn
- A handoff itself consumes one turn (the turn where the LLM chose the handoff tool)
- If `max_turns` is exceeded, the Runner raises `MaxTurnsExceeded`

**Important:** A single `Runner.run()` call may involve multiple agents (via handoffs), but `max_turns` is the **global** limit across all agents within that run.

### 5.4 Handling `MaxTurnsExceeded`

```python
from agents import MaxTurnsExceeded

try:
    result = await Runner.run(agent, "Help", max_turns=5)
except MaxTurnsExceeded as e:
    print(f"Agent loop exceeded {e.max_turns} turns")
    # Handle gracefully -- perhaps return last partial output

# Or use error_handlers for structured handling
result = await Runner.run(
    agent, "Help",
    max_turns=5,
    error_handlers={"max_turns": my_max_turns_handler},
)
```

### 5.5 Nesting with Agents-as-Tools

When using `as_tool()`, nesting is also possible but has different semantics:

```python
# Sub-agent can itself have tools and even handoffs
specialist_agent = Agent(
    name="Specialist",
    tools=[search_tool],
    handoffs=[deeper_specialist],  # Handoff within a tool call
)

orchestrator = Agent(
    name="Orchestrator",
    tools=[
        specialist_agent.as_tool(
            tool_name="specialist",
            tool_description="Ask the specialist",
            max_turns=5,  # Limit the sub-agent's execution
        )
    ],
)
```

Each `as_tool()` invocation creates a **separate `Runner.run()` call** for the sub-agent. The sub-agent's `max_turns` is independent of the parent's `max_turns`.

---

## 6. Tool Access and Scoping

### 6.1 Tools Are Scoped Per Agent

Each agent has its own `tools` list. When a handoff occurs, the target agent's tools replace the previous agent's tools in the LLM's tool list.

```python
billing_agent = Agent(
    name="Billing",
    tools=[get_invoice, process_payment, refund_charge],  # Billing-specific tools
)

tech_agent = Agent(
    name="Technical",
    tools=[search_docs, run_diagnostic, restart_service],  # Tech-specific tools
)

triage_agent = Agent(
    name="Triage",
    tools=[get_user_info],  # Only triage tools
    handoffs=[billing_agent, tech_agent],
)
```

When `triage_agent` hands off to `billing_agent`:
- `get_user_info` is **removed** from the tool list
- `get_invoice`, `process_payment`, `refund_charge` are **added**
- Plus `transfer_to_*` tools for `billing_agent`'s own handoffs (if any)

### 6.2 No Implicit Tool Sharing

There is no mechanism for tools to be automatically shared across agents during handoffs. If you want multiple agents to use the same tool, you must explicitly add it to each agent's `tools` list:

```python
# Shared tool
shared_lookup = get_user_info

billing_agent = Agent(name="Billing", tools=[shared_lookup, get_invoice])
tech_agent = Agent(name="Technical", tools=[shared_lookup, search_docs])
```

### 6.3 MCP Servers Are Also Scoped Per Agent

```python
billing_mcp = MCPServerStreamableHttp(url="https://billing-mcp.example.com/mcp")
tech_mcp = MCPServerStreamableHttp(url="https://tech-mcp.example.com/mcp")

billing_agent = Agent(name="Billing", mcp_servers=[billing_mcp])
tech_agent = Agent(name="Technical", mcp_servers=[tech_mcp])
```

### 6.4 Conditional Tool Enabling

Tools can be dynamically enabled/disabled at runtime:

```python
@function_tool(is_enabled=lambda ctx, agent: ctx.context.is_admin)
async def admin_tool(ctx: RunContextWrapper[AppContext]) -> str:
    ...

# Or for agents-as-tools:
specialist.as_tool(
    tool_name="specialist",
    tool_description="...",
    is_enabled=lambda ctx, agent: ctx.context.language == "spanish",
)
```

Disabled tools are completely hidden from the LLM -- they do not appear in the tool list.

### 6.5 Tool Isolation in Agents-as-Tools

When a sub-agent runs via `as_tool()`, its tool execution happens in a **separate agent loop**. The sub-agent's tool calls do not appear in the parent agent's message history (unless explicitly surfaced via `custom_output_extractor`).

---

## 7. Guardrails Across Agent Boundaries

### 7.1 Input Guardrails Scope

Input guardrails on an agent **only run when that agent is the first agent in the workflow**:

```python
agent_a = Agent(
    name="Agent A",
    input_guardrails=[my_input_guard],  # Runs if Agent A is the starting agent
    handoffs=[agent_b],
)

agent_b = Agent(
    name="Agent B",
    input_guardrails=[another_guard],   # Does NOT run if Agent B is reached via handoff from A
)
```

This means: if `Runner.run(agent_a, ...)` starts with Agent A, then Agent A's input guardrails run. If Agent A hands off to Agent B, Agent B's input guardrails do **not** fire -- because Agent B is not the initial agent.

### 7.2 Output Guardrails Scope

Output guardrails on an agent **only run when that agent is the last agent** (produces the final output):

```python
agent_a = Agent(
    name="Agent A",
    output_guardrails=[guard_a],  # Runs only if Agent A produces the final output
    handoffs=[agent_b],
)

agent_b = Agent(
    name="Agent B",
    output_guardrails=[guard_b],  # Runs if Agent B produces the final output
)
```

If Agent A hands off to Agent B and Agent B produces the final answer, only `guard_b` fires.

### 7.3 Global Guardrails via RunConfig

To enforce guardrails across all agent boundaries, use `RunConfig`:

```python
run_config = RunConfig(
    input_guardrails=[global_input_guard],   # Always runs on initial input
    output_guardrails=[global_output_guard], # Always runs on final output
)

result = await Runner.run(triage_agent, "Help", run_config=run_config)
```

`RunConfig` guardrails apply regardless of which agent is first or last.

### 7.4 Tool Guardrails

Tool guardrails are scoped to the specific `@function_tool` they decorate. They run whenever that tool is called, regardless of which agent invokes it:

```python
@tool_input_guardrail
async def validate_amount(ctx, tool_context, agent, data) -> GuardrailFunctionOutput:
    if data.get("amount", 0) > 10000:
        return GuardrailFunctionOutput(tripwire_triggered=True)
    return GuardrailFunctionOutput(tripwire_triggered=False)

@function_tool
@validate_amount
async def process_payment(amount: float) -> str:
    ...
```

### 7.5 Guardrail Execution Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| Parallel (default) | Guardrail runs concurrently with agent LLM call | Latency optimization |
| Blocking | Guardrail completes before agent starts | Token cost protection |

```python
@input_guardrail(run_in_parallel=False)  # Blocking mode
async def strict_guard(ctx, agent, input) -> GuardrailFunctionOutput:
    ...
```

### 7.6 Tripwire Exceptions

When a guardrail triggers:
- `InputGuardrailTripwireTriggered` -- for input guardrails
- `OutputGuardrailTripwireTriggered` -- for output guardrails
- These immediately halt the agent run

---

## 8. Runner and Multi-Agent Execution

### 8.1 Runner Methods (Full Signatures)

```python
class Runner:
    @classmethod
    async def run(
        cls,
        starting_agent: Agent[TContext],
        input: str | list[TResponseInputItem] | RunState[TContext],
        *,
        context: TContext | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,   # 10
        hooks: RunHooks[TContext] | None = None,
        run_config: RunConfig | None = None,
        error_handlers: RunErrorHandlers[TContext] | None = None,
        previous_response_id: str | None = None,
        auto_previous_response_id: bool = False,
        conversation_id: str | None = None,
        session: Session | None = None,
    ) -> RunResult: ...

    @classmethod
    def run_sync(cls, ...) -> RunResult: ...  # Same params, sync wrapper

    @classmethod
    def run_streamed(cls, ...) -> RunResultStreaming: ...  # Same params + streaming
```

### 8.2 The Agent Loop with Handoffs

```
Runner.run(starting_agent, input) called
    |
    v
[Turn 1] current_agent = starting_agent
    |
    +-- Call LLM with current_agent's instructions, tools, handoffs, history
    |
    +-- LLM response includes tool_call: "transfer_to_refund_agent"
    |
    +-- Runner detects handoff:
    |     1. Execute on_handoff callback (if any)
    |     2. Apply input_filter (if any) to conversation history
    |     3. Set current_agent = refund_agent
    |     4. Increment turn counter
    |
    v
[Turn 2] current_agent = refund_agent
    |
    +-- Call LLM with refund_agent's instructions, tools, new history
    |
    +-- LLM response includes tool_call: "process_refund"
    |
    +-- Runner executes process_refund tool, appends result
    |     Increment turn counter
    |
    v
[Turn 3] current_agent = refund_agent (still)
    |
    +-- Call LLM with tool results
    |
    +-- LLM response is final text output (no tool calls, no handoffs)
    |
    +-- Output guardrails run (refund_agent is the last agent)
    |
    v
Return RunResult(final_output=..., last_agent=refund_agent)
```

### 8.3 RunResult Fields

```python
@dataclass
class RunResult:
    final_output: Any           # The final response (typed if output_type set)
    last_agent: Agent           # Which agent produced the final output
    # ... additional fields for usage, trace info, etc.

    def to_input_list(self) -> list[TResponseInputItem]:
        """Convert to input format for chaining to next run."""
        ...
```

### 8.4 Multi-Turn Conversations with Handoffs

The `session` parameter enables conversation persistence across runs. When using sessions, handoff history is preserved:

```python
from agents import SQLiteSession

session = SQLiteSession("user_123", "conversations.db")

# Run 1: Triage hands off to billing
result1 = await Runner.run(triage_agent, "I have a billing question", session=session)
# result1.last_agent might be billing_agent

# Run 2: Continue with the same session -- billing agent retains context
result2 = await Runner.run(result1.last_agent, "What about my invoice?", session=session)
```

### 8.5 Streaming with Handoffs

```python
result = Runner.run_streamed(triage_agent, "Help me")

async for event in result.stream_events():
    # Events come from whichever agent is currently active
    # Handoffs may occur mid-stream, changing the active agent
    if event.type == "raw_response_event":
        print(event.data)  # LLM tokens
    elif event.type == "agent_updated_stream_event":
        print(f"Agent changed to: {event.new_agent.name}")
    elif event.type == "run_item_stream_event":
        print(f"Item: {event.item}")
```

The `agent_updated_stream_event` fires when a handoff occurs during streaming, allowing the consumer to track which agent is currently active.

---

## 9. Tracing Across Agent Handoffs

### 9.1 Automatic Trace Structure

A single `Runner.run()` call produces a single trace, even if multiple agents are involved:

```
Trace: "Agent workflow"
├── AgentSpan: "Triage agent"
│   ├── GenerationSpan: LLM call (model, input, output, tokens)
│   └── HandoffSpan: Triage -> Refund (from_agent, to_agent)
├── AgentSpan: "Refund agent"
│   ├── GenerationSpan: LLM call
│   ├── FunctionSpan: "process_refund" (input, output)
│   └── GenerationSpan: LLM call (final response)
└── GuardrailSpan: "output_guard" (triggered: false)
```

### 9.2 Span Types for Multi-Agent

| Span Creator | Purpose | Key Fields |
|-------------|---------|------------|
| `agent_span(name, handoffs, tools, output_type)` | Agent execution boundary | Agent name, available handoffs/tools |
| `handoff_span(from_agent, to_agent)` | Agent-to-agent transition | Source and target agent names |
| `generation_span(input, output, model, usage)` | LLM API call | Full I/O, model config, token counts |
| `function_span(name, input, output)` | Tool execution | Tool name, arguments, result |
| `guardrail_span(name, triggered)` | Guardrail evaluation | Whether tripwire fired |
| `custom_span(name, data)` | User-defined events | Arbitrary data dict |
| `mcp_tools_span(server, result)` | MCP tool discovery | Server name, discovered tool names |

### 9.3 Creating Custom Traces Around Multi-Agent Flows

```python
from agents import trace, custom_span, Runner

async def multi_agent_workflow(user_input: str):
    with trace("Customer Support Flow", group_id="conv_456"):
        # Phase 1: Classification
        with custom_span("classification"):
            classify_result = await Runner.run(classifier_agent, user_input)

        # Phase 2: Specialized handling (with handoffs)
        category = classify_result.final_output.category
        if category == "billing":
            result = await Runner.run(billing_triage_agent, user_input)
        else:
            result = await Runner.run(tech_triage_agent, user_input)

        # Phase 3: Quality check
        with custom_span("quality_check"):
            await verify_response(result.final_output)

    return result
```

### 9.4 Tracing Configuration

```python
run_config = RunConfig(
    workflow_name="Customer Support",     # Logical name for the trace
    trace_id="trace_abc123",             # Custom trace ID
    group_id="conversation_789",         # Link related traces
    trace_metadata={"team": "support"},  # Custom metadata
    trace_include_sensitive_data=False,   # Omit LLM I/O from traces
    tracing_disabled=False,              # Enable (default)
)
```

### 9.5 Cross-Agent Trace Continuity

Traces automatically span across handoffs within a single `Runner.run()`. The trace hierarchy shows the full agent chain, making it easy to debug multi-agent flows.

For **separate** `Runner.run()` calls (code-level orchestration), use `group_id` to link traces:

```python
with trace("Multi-step workflow", group_id="session_123"):
    result1 = await Runner.run(agent_a, "Step 1")
    result2 = await Runner.run(agent_b, result1.to_input_list())
    # Both runs appear under the same trace
```

---

## 10. MCP Integration in Multi-Agent Setups

### 10.1 MCP Servers Per Agent

Each agent can have its own MCP servers, providing agent-specific tool discovery:

```python
from agents.mcp import MCPServerStdio, MCPServerStreamableHttp

# Agent with local filesystem MCP
fs_agent = Agent(
    name="File Agent",
    mcp_servers=[
        MCPServerStdio(
            name="Filesystem",
            params={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]}
        )
    ],
)

# Agent with remote API MCP
api_agent = Agent(
    name="API Agent",
    mcp_servers=[
        MCPServerStreamableHttp(
            name="API Server",
            url="https://api-mcp.example.com/mcp",
            cache_tools_list=True,
        )
    ],
)

# Triage routes to appropriate specialist
triage = Agent(
    name="Triage",
    handoffs=[fs_agent, api_agent],
)
```

### 10.2 Hosted MCP (HostedMCPTool)

HostedMCPTool delegates tool operations to OpenAI's infrastructure:

```python
from agents import Agent, HostedMCPTool

agent = Agent(
    name="Research Agent",
    tools=[
        HostedMCPTool(
            tool_config={
                "type": "mcp",
                "server_label": "gitmcp",
                "server_url": "https://gitmcp.io/openai/codex",
                "require_approval": "never",
            }
        )
    ],
)
```

### 10.3 MCPServerManager for Multi-Server Setups

```python
from agents.mcp import MCPServerManager

servers = [billing_mcp, tech_mcp, search_mcp]

async with MCPServerManager(servers, drop_failed_servers=True) as manager:
    # Only successfully connected servers are used
    agent = Agent(
        name="Multi-MCP Agent",
        mcp_servers=manager.active_servers,
    )

    # Check failures
    for server in manager.failed_servers:
        print(f"Failed to connect: {server.name}")

    # Retry failed servers
    await manager.reconnect(failed_only=True)
```

### 10.4 Tool Filtering for MCP

Control which MCP tools are exposed to each agent:

```python
from agents.mcp import create_static_tool_filter

# Static filtering
agent = Agent(
    name="Limited Agent",
    mcp_servers=[server],
    mcp_config={
        "tool_filter": create_static_tool_filter(
            allowed_tool_names=["read_file", "list_directory"],
            # Or: blocked_tool_names=["delete_file", "write_file"]
        )
    },
)

# Dynamic filtering
async def context_aware_filter(context: ToolFilterContext, tool) -> bool:
    """Only allow write tools for admin users."""
    if tool.name.startswith("write_") or tool.name.startswith("delete_"):
        return context.run_context.context.is_admin
    return True
```

### 10.5 MCP Approval Policies

```python
# Global approval
server = MCPServerStreamableHttp(
    url="...",
    require_approval="always",  # or "never"
)

# Per-tool approval
server = MCPServerStreamableHttp(
    url="...",
    require_approval={
        "delete_file": "always",
        "read_file": "never",
        "write_file": "always",
    },
)

# Callback-based approval
def approve_tool(request: MCPToolApprovalRequest) -> MCPToolApprovalFunctionResult:
    if request.tool_name in SAFE_TOOLS:
        return {"approve": True}
    return {"approve": False, "reason": "Tool requires manual approval"}
```

---

## 11. Concurrency and Parallel Execution

### 11.1 `asyncio.gather` Pattern (Code-Level Parallelism)

The most flexible approach for running agents in parallel:

```python
import asyncio
from agents import Agent, Runner

# Define specialized agents
sentiment_agent = Agent(name="Sentiment", instructions="Analyze sentiment", output_type=SentimentResult)
summary_agent = Agent(name="Summary", instructions="Summarize text", output_type=SummaryResult)
entity_agent = Agent(name="Entities", instructions="Extract entities", output_type=EntityResult)
recommend_agent = Agent(name="Recommend", instructions="Generate recommendation", output_type=RecommendResult)

# Fan-out: run all agents in parallel
async def analyze_parallel(text: str):
    parallel_agents = [sentiment_agent, summary_agent, entity_agent, recommend_agent]

    results = await asyncio.gather(
        *(Runner.run(agent, text) for agent in parallel_agents)
    )

    # Fan-in: merge results
    labeled_outputs = [
        f"### {resp.last_agent.name}\n{resp.final_output}"
        for resp in results
    ]
    merged = "\n\n".join(labeled_outputs)

    # Meta-agent synthesizes final output
    meta_agent = Agent(name="Meta", instructions="Synthesize all analyses into a report")
    final = await Runner.run(meta_agent, merged)
    return final.final_output
```

**Advantages:** Lowest latency, maximum control, deterministic execution order.

### 11.2 Agents-as-Tools with `parallel_tool_calls` (LLM-Driven Parallelism)

```python
from agents import Agent, ModelSettings

meta_agent = Agent(
    name="Meta Agent",
    instructions="Analyze the given text using all available specialists.",
    model_settings=ModelSettings(parallel_tool_calls=True),  # Enable parallel tool calls
    tools=[
        sentiment_agent.as_tool(
            tool_name="analyze_sentiment",
            tool_description="Analyze the sentiment of the text",
        ),
        summary_agent.as_tool(
            tool_name="summarize",
            tool_description="Summarize the text",
        ),
        entity_agent.as_tool(
            tool_name="extract_entities",
            tool_description="Extract named entities",
        ),
    ],
)

# LLM decides which tools to call and can call multiple simultaneously
result = await Runner.run(meta_agent, "Analyze this review: ...")
```

**Advantages:** Dynamic tool selection, LLM plans the execution, less code.
**Trade-off:** Higher latency from planning overhead, less predictable.

### 11.3 Comparison Table

| Factor | asyncio.gather | Agents-as-Tools (parallel) |
|--------|---------------|---------------------------|
| **Latency** | Lowest | Higher (LLM planning overhead) |
| **Control** | Full deterministic control | LLM decides what to call |
| **Flexibility** | Fixed execution plan | Dynamic, adaptive |
| **Code complexity** | More boilerplate | Less code |
| **Tool visibility** | Each agent isolated | Tools visible to meta-agent |
| **Error handling** | Standard asyncio patterns | Tool error handling |

### 11.4 Parallel Tool Execution Within a Single Agent

Even within a single agent, the LLM can request multiple tool calls in one response. These are executed concurrently by default:

```python
agent = Agent(
    name="Researcher",
    model_settings=ModelSettings(parallel_tool_calls=True),
    tools=[search_web, search_docs, query_database],
)
# LLM can call all three tools simultaneously in one turn
```

### 11.5 Async Context Safety

The SDK uses Python `contextvar` for trace context, ensuring that parallel async operations maintain proper trace parentage:

```python
# Safe: each gather branch gets its own trace context
async with trace("Parallel Analysis"):
    results = await asyncio.gather(
        Runner.run(agent_a, "Task A"),
        Runner.run(agent_b, "Task B"),
        Runner.run(agent_c, "Task C"),
    )
    # Each run creates its own sub-trace, all under the parent
```

---

## 12. Example Patterns from the SDK Repository

The [`examples/agent_patterns`](https://github.com/openai/openai-agents-python/tree/main/examples/agent_patterns) directory contains reference implementations:

| Example | Pattern | Description |
|---------|---------|-------------|
| `routing.py` | Handoff | Triage agent routes to specialized sub-agents based on criteria |
| `agents_as_tools.py` | Manager | Central agent invokes sub-agents as tool calls |
| `agents_as_tools_streaming.py` | Manager + Streaming | Uses `on_stream` to tap into nested agent events |
| `agents_as_tools_structured.py` | Manager + Structured I/O | Uses `parameters` for typed sub-agent input |
| `agents_as_tools_conditional.py` | Manager + Dynamic | Conditional agent-as-tool invocation |
| `deterministic.py` | Sequential Chaining | One agent's output feeds into the next agent's input |
| `parallelization.py` | Parallel | Multiple agents run simultaneously, best result selected |
| `llm_as_a_judge.py` | Evaluation Loop | Second model evaluates and provides feedback on initial output |
| `input_guardrails.py` | Guardrails | Input validation before agent execution |
| `output_guardrails.py` | Guardrails | Output validation after agent execution |
| `streaming_guardrails.py` | Guardrails + Streaming | Guardrails within streaming contexts |
| `forcing_tool_use.py` | Tool Control | Enforcing specific tool selection |
| `human_in_the_loop.py` | Approval | Pause for manual approval before sensitive operations |
| `human_in_the_loop_stream.py` | Approval + Streaming | Streaming variant of approval pattern |
| `human_in_the_loop_custom_rejection.py` | Approval + Error | Custom error formatting on rejection |

---

## 13. Summary Comparison: Handoffs vs. Agents-as-Tools

| Aspect | Handoffs | Agents-as-Tools |
|--------|----------|-----------------|
| **Control transfer** | Target agent takes over conversation | Orchestrator retains control |
| **Conversation history** | Full history passed to target (filterable) | Sub-agent sees only tool input |
| **Context (RunContext)** | Same context instance shared | New context for sub-agent run |
| **Tool scope** | Target agent's tools replace previous | Sub-agent's tools are isolated |
| **LLM representation** | `transfer_to_<name>` tool | Custom-named function tool |
| **Turn counting** | Shared `max_turns` across all agents | Separate `max_turns` per sub-agent |
| **Guardrails** | Input: first agent only; Output: last agent only | Each sub-agent can have its own |
| **Tracing** | Single trace spans all handoffs | Sub-agent run creates nested spans |
| **Nesting depth** | Unlimited (bounded by `max_turns`) | Unlimited (each as_tool creates new run) |
| **Circular references** | Possible (use `max_turns` to bound) | Not applicable (manager always retains control) |
| **Streaming** | `agent_updated_stream_event` on handoff | `on_stream` callback for nested events |
| **Pattern name** | Peer delegation / routing | Manager / orchestrator |
| **Best for** | Specialized routing, escalation chains | Parallel sub-tasks, aggregation |

---

## 14. Sources

- [OpenAI Agents SDK - Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [OpenAI Agents SDK - Agents](https://openai.github.io/openai-agents-python/agents/)
- [OpenAI Agents SDK - Orchestrating Multiple Agents](https://openai.github.io/openai-agents-python/multi_agent/)
- [OpenAI Agents SDK - Running Agents](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI Agents SDK - Tools](https://openai.github.io/openai-agents-python/tools/)
- [OpenAI Agents SDK - Context Management](https://openai.github.io/openai-agents-python/context/)
- [OpenAI Agents SDK - Guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenAI Agents SDK - Tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenAI Agents SDK - MCP](https://openai.github.io/openai-agents-python/mcp/)
- [OpenAI Agents SDK - Runner API Reference](https://openai.github.io/openai-agents-python/ref/run/)
- [OpenAI Agents SDK - Agent API Reference](https://openai.github.io/openai-agents-python/ref/agent/)
- [OpenAI Agents SDK - Handoffs API Reference](https://openai.github.io/openai-agents-python/ref/handoffs/)
- [OpenAI Agents SDK - Handoff Filters Reference](https://openai.github.io/openai-agents-python/ref/extensions/handoff_filters/)
- [OpenAI Agents SDK - Lifecycle Reference](https://openai.github.io/openai-agents-python/ref/lifecycle/)
- [OpenAI Agents SDK - Tracing Spans Reference](https://openai.github.io/openai-agents-python/ref/tracing/create/)
- [OpenAI Cookbook: Parallel Agents](https://developers.openai.com/cookbook/examples/agents_sdk/parallel_agents/)
- [OpenAI Cookbook: Multi-Agent Portfolio Collaboration](https://developers.openai.com/cookbook/examples/agents_sdk/multi-agent-portfolio-collaboration/multi_agent_portfolio_collaboration/)
- [OpenAI Cookbook: Orchestrating Agents -- Routines and Handoffs](https://cookbook.openai.com/examples/orchestrating_agents)
- [OpenAI: A Practical Guide to Building Agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)
- [GitHub: openai/openai-agents-python](https://github.com/openai/openai-agents-python)
- [GitHub: openai/openai-agents-python -- agent_patterns examples](https://github.com/openai/openai-agents-python/tree/main/examples/agent_patterns)
