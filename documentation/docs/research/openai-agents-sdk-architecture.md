# OpenAI Agents SDK Architecture Research

> **Date:** 2026-02-24
> **Subject:** Deep technical analysis of the OpenAI Agents SDK (formerly Swarm)
> **Repo:** [openai/openai-agents-python](https://github.com/openai/openai-agents-python)
> **Docs:** [openai.github.io/openai-agents-python](https://openai.github.io/openai-agents-python/)
> **License:** MIT
> **Language:** Python 3.10+
> **Package:** `openai-agents` (PyPI)

---

## 1. Overview

The **OpenAI Agents SDK** is OpenAI's official, production-grade Python framework for building single-agent and multi-agent workflows. It is a lightweight, provider-agnostic framework with minimal abstractions, designed so that developers can build agentic applications without heavy boilerplate.

### Evolution from Swarm

The SDK is the direct successor to **OpenAI Swarm**, an experimental/educational framework released in 2024. Swarm explored ergonomic, lightweight multi-agent orchestration but was explicitly not intended for production use. The Agents SDK retains Swarm's core philosophy -- simplicity, minimal abstractions, routine/handoff patterns -- but adds production-grade features:

- Built-in tracing and observability
- Guardrails (input, output, and tool-level)
- Session/memory management
- MCP (Model Context Protocol) integration
- Structured output via Pydantic
- Streaming support
- Support for 100+ LLMs via LiteLLM, not just OpenAI models

### Core Philosophy

The SDK is built around a small set of primitives:

| Primitive | Purpose |
|-----------|---------|
| **Agent** | An LLM configured with instructions, tools, guardrails, and handoffs |
| **Runner** | Orchestrates the agent loop: model calls, tool execution, handoffs |
| **Tools** | Functions (local or hosted) the agent can invoke |
| **Handoffs** | Transfer control between peer agents |
| **Guardrails** | Input/output validation and safety checks |
| **Sessions** | Persistent conversation history across runs |
| **Tracing** | Built-in observability for debugging and monitoring |

### Installation

```bash
pip install openai-agents
# Optional extras:
pip install 'openai-agents[voice]'   # Voice/realtime support
pip install 'openai-agents[redis]'   # Redis session backend
```

### Hello World

```python
from agents import Agent, Runner

agent = Agent(name="Assistant", instructions="You are a helpful assistant")
result = Runner.run_sync(agent, "Write a haiku about recursion in programming.")
print(result.final_output)
# => "Code calls itself deep, / Layers of logic unfold, / Base case ends the loop."
```

---

## 2. Agent Loop Lifecycle

The agent loop is the core execution model. The `Runner` class manages it.

### Runner Class

The `Runner` is a classmethod-based orchestrator (no instantiation needed). It provides three entry points:

| Method | Signature | Returns | Notes |
|--------|-----------|---------|-------|
| `Runner.run()` | `async` | `RunResult` | Primary async method |
| `Runner.run_sync()` | sync | `RunResult` | Sync wrapper around `.run()` |
| `Runner.run_streamed()` | `async` | `RunResultStreaming` | Streams LLM events as received |

#### `Runner.run()` Full Signature

```python
@classmethod
async def run(
    starting_agent: Agent[TContext],
    input: str | list[TResponseInputItem] | RunState[TContext],
    *,
    context: TContext | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    hooks: RunHooks[TContext] | None = None,
    run_config: RunConfig | None = None,
    error_handlers: RunErrorHandlers[TContext] | None = None,
    previous_response_id: str | None = None,
    auto_previous_response_id: bool = False,
    conversation_id: str | None = None,
    session: Session | None = None,
) -> RunResult
```

### The Loop, Step by Step

```
User Input
    |
    v
[1] Call LLM with current agent's model, instructions, tools, and message history
    |
    v
[2] LLM returns a response (may include tool calls, handoffs, or final output)
    |
    +---> Final output? (matches agent.output_type, or plain text with no tool calls/handoffs)
    |         YES --> Return RunResult, loop terminates
    |
    +---> Handoff? (transfer_to_<agent_name> tool call)
    |         YES --> Set current agent = target agent, go to [1]
    |
    +---> Tool calls?
              YES --> Execute tool calls, append tool result messages, go to [1]
```

### Termination Conditions

- **With `output_type`:** Loop runs until the LLM produces structured output matching the Pydantic model.
- **Without `output_type`:** Loop runs until the LLM produces a text message with no tool calls and no handoffs.
- **`max_turns` exceeded:** Raises `MaxTurnsExceeded` exception.
- **Guardrail tripwire:** Raises `InputGuardrailTripwireTriggered` or `OutputGuardrailTripwireTriggered`.

### RunConfig

`RunConfig` is a dataclass controlling run-level behavior:

| Field | Type | Purpose |
|-------|------|---------|
| `model` | `str \| Model \| None` | Override model for entire run |
| `model_provider` | `ModelProvider` | Resolve model name strings to Model objects |
| `model_settings` | `ModelSettings \| None` | Global model parameter overrides |
| `max_turns` | (via `run()` arg) | Turn limit |
| `handoff_input_filter` | `HandoffInputFilter \| None` | Global filter for handoff inputs |
| `nest_handoff_history` | `bool` | Collapse prior transcripts on handoff |
| `handoff_history_mapper` | `HandoffHistoryMapper \| None` | Custom history mapping on handoff |
| `input_guardrails` | `list[InputGuardrail] \| None` | Initial input validation |
| `output_guardrails` | `list[OutputGuardrail] \| None` | Final output validation |
| `tracing_disabled` | `bool` | Disable tracing |
| `tracing` | `TracingConfig \| None` | Tracing API key, etc. |
| `trace_include_sensitive_data` | `bool` | Include sensitive data in traces (default True) |
| `workflow_name` | `str` | Name for trace grouping |
| `trace_id` | `str \| None` | Custom trace ID |
| `group_id` | `str \| None` | Group multiple traces (e.g., same conversation) |
| `call_model_input_filter` | `CallModelInputFilter \| None` | Preprocess input right before LLM call |
| `tool_error_formatter` | `ToolErrorFormatter \| None` | Custom error message formatting |
| `session_settings` | `SessionSettings \| None` | Session behavior config |

### RunResult and RunResultStreaming

`RunResult` contains:
- `final_output` -- the agent's final response (typed if `output_type` set)
- Complete execution metadata (usage, traces, etc.)

`RunResultStreaming` provides:
- `.stream_events()` -- async iterator yielding LLM events as they arrive

---

## 3. Agent Definition

### Agent Class

The `Agent` class is generic over a context type `TContext`:

```python
from agents import Agent

agent = Agent[MyContext](
    name="Triage agent",           # Required: unique identifier
    instructions="...",             # System prompt (static str or dynamic callable)
    model="gpt-4.1",               # Model name or Model instance
    model_settings=ModelSettings(   # LLM parameter tuning
        temperature=0.7,
        tool_choice="auto",
    ),
    tools=[get_weather, search],    # List of tools
    mcp_servers=[mcp_server],       # MCP tool providers
    handoffs=[agent_a, agent_b],    # Peer agents for delegation
    output_type=MyOutputModel,      # Pydantic model for structured output
    input_guardrails=[my_guard],    # Input validation
    output_guardrails=[out_guard],  # Output validation
    hooks=MyAgentHooks(),           # Lifecycle callbacks
    handoff_description="...",      # Description used in handoff tool
    tool_use_behavior="run_llm_again",  # How tool results are handled
    reset_tool_choice=True,         # Reset tool_choice after forced tool use
)
```

### Instructions (System Prompt)

Instructions can be **static** or **dynamic**:

```python
# Static
agent = Agent(name="Bot", instructions="You are a helpful assistant.")

# Dynamic -- receives context and agent reference
def dynamic_instructions(
    context: RunContextWrapper[UserContext],
    agent: Agent[UserContext]
) -> str:
    return f"The user's name is {context.context.name}. Help them."

agent = Agent(name="Bot", instructions=dynamic_instructions)
```

Dynamic instructions are evaluated at each turn, enabling context-dependent system prompts.

### Model Selection

- Default model: `gpt-4.1` (configurable via `OPENAI_DEFAULT_MODEL` env var)
- Per-agent: `agent.model = "gpt-5.2"` or a `Model` instance
- Per-run: `RunConfig(model="gpt-5-nano")`
- Non-OpenAI: `model="litellm/anthropic/claude-3-5-sonnet"` via LiteLLM integration

Two OpenAI model backends:
- `OpenAIResponsesModel` (default, recommended) -- uses the Responses API
- `OpenAIChatCompletionsModel` -- uses the Chat Completions API

### ModelSettings

```python
from agents import ModelSettings

ModelSettings(
    temperature=0.7,
    top_p=0.9,
    frequency_penalty=0.0,
    presence_penalty=0.0,
    tool_choice="auto",           # "auto", "required", "none", or specific tool name
    parallel_tool_calls=True,
    max_tokens=4096,
    reasoning={"effort": "high"}, # For reasoning models (GPT-5.x)
    extra_args={"service_tier": "default", "user": "user-123"},
)
```

### Structured Output (`output_type`)

When `output_type` is set, the LLM uses structured outputs (JSON mode constrained to the schema):

```python
from pydantic import BaseModel

class CalendarEvent(BaseModel):
    name: str
    date: str
    participants: list[str]

agent = Agent(
    name="Calendar extractor",
    instructions="Extract calendar events from text",
    output_type=CalendarEvent,
)
# result.final_output will be a CalendarEvent instance
```

### `tool_use_behavior`

Controls what happens after tool execution:

| Value | Behavior |
|-------|----------|
| `"run_llm_again"` (default) | Feed tool results back to LLM for synthesis |
| `"stop_on_first_tool"` | Use first tool's output as the final response |
| `StopAtTools(stop_at_tool_names=[...])` | Stop at specific named tools |
| `Callable` | Custom function returning `ToolsToFinalOutputResult` |

### Clone

Agents can be duplicated and modified:

```python
robot_agent = pirate_agent.clone(name="Robot", instructions="Write like a robot")
```

---

## 4. Tool System

### Tool Categories

| Category | Runs Where | Examples |
|----------|-----------|----------|
| **Function tools** | Locally (your process) | `@function_tool` decorated functions |
| **Hosted tools** | On OpenAI servers | `WebSearchTool`, `FileSearchTool`, `CodeInterpreterTool`, `ImageGenerationTool` |
| **Local runtime tools** | Locally | `ComputerTool`, `LocalShellTool`, `ShellTool`, `ApplyPatchTool` |
| **MCP tools** | On MCP servers | Tools discovered from MCP server `list_tools()` |
| **Agents-as-tools** | Locally (sub-agent run) | `agent.as_tool(...)` |

### Function Tools (`@function_tool`)

The primary way to define custom tools:

```python
from agents import function_tool, RunContextWrapper

@function_tool
async def fetch_weather(location: str) -> str:
    """Fetch the weather for a given location.

    Args:
        location: The city or region to check.
    """
    # ... API call ...
    return "sunny, 72F"
```

Features:
- **Auto-schema generation** from type hints and docstrings (Google, Sphinx, NumPy formats supported via `griffe`)
- **Pydantic validation** of arguments via `Field` constraints
- **Context access**: First arg can be `RunContextWrapper[TContext]` (not sent to LLM)
- **Sync or async** functions supported
- **Configurable timeouts**: `@function_tool(timeout=5.0)`, with `timeout_behavior` of `"error_as_result"` (default) or `"raise_exception"`
- **Error handling**: `failure_error_function` for custom error messages

#### Decorator Parameters

```python
@function_tool(
    name_override="my_tool",       # Override auto-detected name
    timeout=10.0,                  # Seconds
    timeout_behavior="error_as_result",
    failure_error_function=my_handler,
)
```

#### FunctionTool (Manual Construction)

```python
from agents import FunctionTool

tool = FunctionTool(
    name="process_user",
    description="Processes extracted user data",
    params_json_schema=MyArgs.model_json_schema(),
    on_invoke_tool=my_async_handler,  # async (ToolContext, str) -> str
)
```

### Tool Return Types

Tools can return:
- **`str`** -- plain text
- **`ToolOutputText`** -- explicit text wrapper
- **`ToolOutputImage`** -- base64 or URL image data
- **`ToolOutputFileContent`** -- file content with filename
- **`list`** -- mixed list of the above types

### Hosted Tools

```python
from agents import Agent, WebSearchTool, FileSearchTool, CodeInterpreterTool

agent = Agent(
    name="Research assistant",
    tools=[
        WebSearchTool(),              # Web search with optional filters
        FileSearchTool(               # Vector store retrieval
            vector_store_ids=["vs_123"],
            max_num_results=5,
        ),
        CodeInterpreterTool(),        # Sandboxed Python execution
    ],
)
```

Additional hosted tools:
- `ImageGenerationTool` -- image generation from prompts
- `HostedMCPTool` -- remote MCP server tool
- `ShellTool` -- hosted container shell execution (with `container_auto` or `container_reference` environments)

### Agents as Tools

An agent can be exposed as a tool (manager/orchestrator pattern) instead of using handoffs:

```python
orchestrator = Agent(
    name="Orchestrator",
    tools=[
        spanish_agent.as_tool(
            tool_name="translate_to_spanish",
            tool_description="Translate text to Spanish",
        ),
        refund_agent.as_tool(
            tool_name="refund_expert",
            tool_description="Handle refund questions",
        ),
    ],
)
```

The orchestrator retains control; sub-agents run as tool calls and return results. Parameters:
- `tool_name`, `tool_description` -- how the LLM sees the tool
- `parameters` -- Pydantic model for structured input schema
- `custom_output_extractor` -- modify sub-agent output before returning
- `needs_approval` -- add human-in-the-loop approval gate
- `is_enabled` -- conditionally enable/disable

---

## 5. Handoffs

Handoffs are the multi-agent delegation mechanism. When an agent hands off, the **target agent takes over the conversation** and receives the full message history.

### How Handoffs Work

1. Each entry in `agent.handoffs` is registered as a tool named `transfer_to_<agent_name>`.
2. When the LLM calls this tool, the Runner switches the current agent to the target.
3. The full conversation history is passed to the new agent.
4. The loop continues with the new agent from step [1].

### Basic Usage

```python
triage_agent = Agent(
    name="Triage",
    instructions="Route to booking or refund agent as appropriate.",
    handoffs=[booking_agent, refund_agent],
)
```

### The `handoff()` Function (Advanced)

For fine-grained control:

```python
from agents import handoff

class EscalationData(BaseModel):
    reason: str

async def on_escalation(ctx: RunContextWrapper[None], input_data: EscalationData):
    print(f"Escalation reason: {input_data.reason}")

custom_handoff = handoff(
    agent=escalation_agent,
    tool_name_override="escalate_to_human",
    tool_description_override="Escalate when the user is upset",
    on_handoff=on_escalation,          # Callback when handoff fires
    input_type=EscalationData,         # Pydantic model for LLM-provided data
    input_filter=my_filter,            # Filter conversation history
    is_enabled=True,                   # Bool or callable for runtime toggling
)
```

### Input Filters

By default, the new agent sees the **entire** conversation history. Input filters let you control this:

```python
def my_filter(data: HandoffInputData) -> HandoffInputData:
    # data.history -- list of prior messages
    # data.pre_handoff_items -- items from the handoff turn
    # data.new_items -- new items to add
    return HandoffInputData(
        history=data.history[-5:],  # Only last 5 messages
        pre_handoff_items=[],
        new_items=data.new_items,
    )
```

Built-in filters in `agents.extensions.handoff_filters`:
- `remove_all_tools` -- strips tool call messages from history

### Nested Handoff History (Beta)

Enable `RunConfig.nest_handoff_history=True` to collapse prior transcripts into summarized messages wrapped in `<CONVERSATION HISTORY>` blocks instead of passing raw history.

### Handoff Prompt Helpers

```python
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX, prompt_with_handoff_instructions

agent = Agent(
    instructions=prompt_with_handoff_instructions("You are a triage agent..."),
    handoffs=[booking_agent, refund_agent],
)
```

### Handoffs vs. Agents-as-Tools

| Aspect | Handoffs | Agents as Tools |
|--------|----------|-----------------|
| Control transfer | Target agent takes over | Orchestrator retains control |
| History | Full history passed | Sub-agent sees only tool input |
| Pattern | Peer delegation | Manager/orchestrator |
| Use case | Specialized routing | Parallel sub-tasks |

---

## 6. Guardrails

Guardrails validate inputs and outputs, providing safety checks and policy enforcement. They use a **tripwire** pattern: if validation fails, the guardrail triggers a tripwire that immediately raises an exception, halting the run.

### Input Guardrails

Run before or in parallel with agent execution. Validate user input.

```python
from agents import input_guardrail, Agent, Runner, GuardrailFunctionOutput

class MathHomeworkCheck(BaseModel):
    is_math_homework: bool
    reasoning: str

guardrail_agent = Agent(
    name="Guardrail check",
    instructions="Check if the input is asking to solve math homework.",
    output_type=MathHomeworkCheck,
)

@input_guardrail
async def math_guardrail(
    ctx: RunContextWrapper[None],
    agent: Agent,
    input: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:
    result = await Runner.run(guardrail_agent, input, context=ctx.context)
    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_math_homework,
    )

agent = Agent(
    name="Math tutor",
    input_guardrails=[math_guardrail],
)
```

### Execution Modes

- **Parallel** (default): Guardrail runs concurrently with agent LLM call. Optimizes latency but may consume tokens before validation fails.
- **Blocking** (`run_in_parallel=False`): Guardrail completes before agent starts. Prevents token consumption on failure.

### Output Guardrails

Validate the agent's final output. Always run after agent completion (no parallel option).

```python
@output_guardrail
async def pii_guardrail(
    ctx: RunContextWrapper[None],
    agent: Agent,
    output: Any,
) -> GuardrailFunctionOutput:
    has_pii = check_for_pii(output)
    return GuardrailFunctionOutput(
        output_info={"has_pii": has_pii},
        tripwire_triggered=has_pii,
    )
```

### Tool Guardrails

Wrap `@function_tool` decorated tools to validate/block individual tool calls:

- **Input tool guardrails**: Run before tool execution; can skip the call, replace the output, or trigger a tripwire.
- **Output tool guardrails**: Run after tool execution; can replace the output or trigger a tripwire.

### Tripwire Exceptions

| Guardrail Type | Exception Raised |
|----------------|-----------------|
| Input guardrail | `InputGuardrailTripwireTriggered` |
| Output guardrail | `OutputGuardrailTripwireTriggered` |
| Tool guardrail | Corresponding tripwire exception |

### Global Guardrails

Guardrails can also be configured at the run level via `RunConfig`:

```python
run_config = RunConfig(
    input_guardrails=[global_input_guard],
    output_guardrails=[global_output_guard],
)
result = await Runner.run(agent, input, run_config=run_config)
```

---

## 7. Context and State

### RunContext / RunContextWrapper

Context is a **dependency-injection** mechanism. You create any Python object to hold state and dependencies, then pass it to `Runner.run()`. Every agent, tool, hook, and guardrail receives a `RunContextWrapper[TContext]` wrapping your object.

```python
from dataclasses import dataclass
from agents import Agent, Runner, RunContextWrapper, function_tool

@dataclass
class AppContext:
    user_id: str
    db_connection: DatabasePool
    preferences: dict

@function_tool
async def get_user_orders(ctx: RunContextWrapper[AppContext], limit: int = 10) -> str:
    db = ctx.context.db_connection
    orders = await db.query(f"SELECT * FROM orders WHERE user_id = '{ctx.context.user_id}' LIMIT {limit}")
    return str(orders)

agent = Agent[AppContext](name="Order agent", tools=[get_user_orders])

app_ctx = AppContext(user_id="u_123", db_connection=pool, preferences={})
result = await Runner.run(agent, "Show my recent orders", context=app_ctx)
```

### RunContextWrapper Fields

| Field | Type | Description |
|-------|------|-------------|
| `context` | `TContext` | Your custom context object |
| `usage` | `Usage` | Token usage for the run so far |
| `tool_input` | `Any \| None` | Structured input for current tool run |
| `turn_input` | `list[TResponseInputItem]` | Internal response item tracking |

### Key Methods

- `is_tool_approved(tool_name, call_id) -> bool | None` -- query approval status
- `approve_tool(approval_item, always_approve=False)` -- approve a tool call
- `reject_tool(approval_item, always_reject=False)` -- reject a tool call
- `get_approval_status(tool_name, call_id)` -- status with fallback resolution

### Critical Design Points

1. **Context is never sent to the LLM.** It is purely local for your code (tools, hooks, guardrails).
2. **All agents, tools, and hooks in a single run share the same context type** (`TContext`).
3. **Context is mutable.** Tools can read from and write to it during execution.
4. **Any Python object works** -- dataclass, Pydantic model, dict, or custom class.

---

## 8. Tracing and Observability

### Architecture

The SDK has a built-in tracing system with three layers:

1. **TraceProvider** -- global singleton, creates traces
2. **BatchTraceProcessor** -- batches traces/spans for efficient export
3. **BackendSpanExporter** -- ships data to the OpenAI backend

### Traces and Spans

- A **Trace** represents a single end-to-end workflow execution.
  - Properties: `workflow_name`, `trace_id`, `group_id`, metadata
- A **Span** represents a single operation within a trace (LLM call, tool execution, etc.).
  - Properties: start/end timestamps, `trace_id`, `parent_id` (for nesting)

### Automatic Instrumentation

The SDK automatically creates spans for:

| Span Type | Function | Tracks |
|-----------|----------|--------|
| Agent span | `agent_span()` | Agent name, handoffs, tools, output type |
| Generation span | `generation_span()` | LLM input/output, model, config, token usage |
| Function span | `function_span()` | Tool function input/output |
| Guardrail span | `guardrail_span()` | Guardrail execution |
| Handoff span | `handoff_span()` | Agent-to-agent transfers |
| Transcription span | `transcription_span()` | Audio transcription |
| Speech span | `speech_span()` | Text-to-speech |

### Custom Traces and Spans

```python
from agents import trace, custom_span, Runner

async def main():
    # Wrap multiple runs in a single trace
    with trace("My Workflow", group_id="conversation_123"):
        result1 = await Runner.run(agent, "Step 1")

        with custom_span("post-processing"):
            processed = transform(result1.final_output)

        result2 = await Runner.run(agent, f"Step 2: {processed}")
```

`trace()` uses Python `contextvar` for concurrent safety. Spans auto-attach to the current trace and nest under the nearest parent span.

### Viewing Traces

- **OpenAI Dashboard**: [platform.openai.com/traces](https://platform.openai.com/traces)
- **External integrations** (20+): Datadog, Weights & Biases, Arize-Phoenix, MLflow, Langfuse, LangSmith, PostHog, AgentOps, and more

### Custom Trace Processors

```python
from agents import add_trace_processor, set_trace_processors

# Add alongside default OpenAI export
add_trace_processor(my_custom_processor)

# Or replace entirely
set_trace_processors([my_custom_processor])
```

### Disabling Tracing

- **Global**: `OPENAI_AGENTS_DISABLE_TRACING=1` environment variable
- **Per-run**: `RunConfig(tracing_disabled=True)`

### Sensitive Data Control

- `RunConfig(trace_include_sensitive_data=False)` -- omit LLM inputs/outputs from traces
- `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA=0` -- environment variable

---

## 9. MCP Integration

The SDK supports [Model Context Protocol](https://modelcontextprotocol.io/) servers as first-class tool providers.

### Transport Types

| Class | Transport | Use Case |
|-------|-----------|----------|
| `MCPServerStdio` | stdin/stdout subprocess | Local tools, CLI-based servers |
| `MCPServerStreamableHttp` | HTTP (Streamable HTTP) | Remote/networked servers |

### MCPServerStdio

Spawns a local subprocess, communicates via stdin/stdout pipes:

```python
from agents.mcp import MCPServerStdio

async with MCPServerStdio(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
) as server:
    agent = Agent(name="FS Agent", mcp_servers=[server])
    result = await Runner.run(agent, "List files in the directory")
```

### MCPServerStreamableHttp

Connects to HTTP-based MCP servers:

```python
from agents.mcp import MCPServerStreamableHttp

async with MCPServerStreamableHttp(
    url="https://my-mcp-server.example.com/mcp",
    cache_tools_list=True,       # Cache tool discovery results
    max_retry_attempts=3,
) as server:
    agent = Agent(name="Remote Agent", mcp_servers=[server])
```

### Tool Discovery

Every agent run calls `list_tools()` on connected MCP servers to discover available tools. Tool definitions are fetched automatically before each model invocation.

### Caching

Remote tool discovery incurs latency. Use `cache_tools_list=True` to cache results. Call `server.invalidate_tools_cache()` to refresh stale definitions.

### Multiple Servers

```python
from agents.mcp import MCPServerManager

servers = [server_a, server_b, server_c]
async with MCPServerManager(servers) as manager:
    agent = Agent(mcp_servers=manager.active_servers)
```

### Agent-Level MCP Config

```python
agent = Agent(
    name="Agent",
    mcp_servers=[server],
    mcp_config={
        "convert_schemas_to_strict": True,   # Enforce strict JSON schemas
        "failure_error_function": None,       # Custom error handling
    },
)
```

---

## 10. Sessions and Memory

Sessions provide automatic conversation history management across multiple `Runner.run()` calls.

### How Sessions Work

1. **Pre-run**: Runner retrieves history from session, prepends to new input.
2. **Execution**: Agent processes combined historical + new items.
3. **Post-run**: New items stored in session automatically.

### Session Implementations

| Session Type | Backend | Notes |
|-------------|---------|-------|
| `SQLiteSession` | SQLite | Default lightweight option (file or in-memory) |
| `AsyncSQLiteSession` | SQLite (async) | Async via `aiosqlite` |
| `RedisSession` | Redis | Shared, low-latency across services |
| `SQLAlchemySession` | Any SQLAlchemy DB | Production-grade, any SQL backend |
| `OpenAIConversationsSession` | OpenAI API | Cloud-hosted via Conversations API |
| `OpenAIResponsesCompactionSession` | Wraps another session | Auto-compacts history via Responses API |
| `EncryptedSession` | Wraps another session | Transparent encryption |
| `DaprSession` | Dapr state stores | 30+ backends (Cosmos DB, DynamoDB, etc.) |
| `AdvancedSQLiteSession` | SQLite | Branching, analytics |

### Session Methods (SessionABC Protocol)

- `get_items()` -- retrieve conversation history
- `add_items()` -- store new items
- `pop_item()` -- remove last item (for correction workflows)
- `clear_session()` -- wipe session data

### Compaction

`OpenAIResponsesCompactionSession` wraps another session and automatically condenses conversation history to manage growing context windows. Compaction can be triggered automatically after each turn or manually during idle periods.

---

## 11. Lifecycle Hooks

### Hook Types

| Hook Class | Scope | Use Case |
|-----------|-------|----------|
| `RunHooks[TContext]` | Entire run (all agents) | Global logging, monitoring |
| `AgentHooks[TContext]` | Single agent | Per-agent behavior customization |

### RunHooks Methods

- `on_agent_start(context, agent)` -- before any agent runs
- `on_agent_end(context, agent, output)` -- after agent produces output
- `on_handoff(context, from_agent, to_agent)` -- when a handoff occurs
- `on_tool_start(context, agent, tool)` -- before tool execution
- `on_tool_end(context, agent, tool, result)` -- after tool execution

### AgentHooks Methods

- `on_start(context, agent)` -- before this specific agent runs
- `on_end(context, agent, output)` -- after this agent produces output
- `on_handoff(context, agent)` -- when this agent is being handed off to
- `on_llm_start(context)` -- just before LLM invocation
- `on_llm_end(context)` -- immediately after LLM call returns

---

## 12. Comparison: Agents SDK vs. Minimal Custom Agent Loop

### Strengths of the Agents SDK

| Aspect | Detail |
|--------|--------|
| **Multi-agent orchestration** | First-class handoffs and agents-as-tools patterns, no custom routing needed |
| **Tool system richness** | Hosted tools (web search, code interpreter, file search), MCP integration, auto-schema from type hints |
| **Guardrails** | Built-in input/output/tool validation with parallel execution and tripwire pattern |
| **Tracing** | Zero-config observability with OpenAI dashboard + 20+ external integrations |
| **Sessions** | Multiple backends (SQLite, Redis, cloud) with auto-compaction |
| **Structured output** | Native Pydantic integration for typed agent responses |
| **Streaming** | `run_streamed()` with event-level granularity |
| **Provider agnostic** | 100+ models via LiteLLM, not locked to OpenAI |
| **Production-grade** | Battle-tested by OpenAI, well-documented, MIT licensed |

### Weaknesses / Trade-offs

| Aspect | Detail |
|--------|--------|
| **Abstraction overhead** | More concepts to learn than a bare loop (Agent, Runner, RunConfig, RunContext, hooks, sessions) |
| **Opinionated loop** | The turn-based loop with fixed termination conditions may not suit all use cases |
| **OpenAI-centric defaults** | Hosted tools only work with OpenAI; tracing defaults to OpenAI backend |
| **Dependency weight** | Pulls in Pydantic, LiteLLM, griffe, etc. -- heavier than a minimal `anthropic` SDK call |
| **Context type rigidity** | All agents/tools in a run must share the same `TContext` type |
| **Limited control over message formatting** | Less flexibility in how messages are constructed vs. raw API calls |
| **Handoff complexity** | Input filters, nested history, handoff mappers add cognitive load for simple use cases |

### When to Choose Each

| Scenario | Recommendation |
|----------|---------------|
| Multi-agent workflows with routing/delegation | Agents SDK |
| Need hosted tools (web search, code interpreter) | Agents SDK |
| Production system needing built-in tracing and guardrails | Agents SDK |
| Minimal single-agent loop with full control | Custom loop |
| Non-standard turn semantics (e.g., streaming mid-turn decisions) | Custom loop |
| Anthropic Claude with provider-specific features | Custom loop (with Anthropic SDK) |
| Learning/prototyping agent concepts | Either (SDK is well-documented) |

---

## Sources

- [OpenAI Agents SDK Documentation](https://openai.github.io/openai-agents-python/)
- [GitHub: openai/openai-agents-python](https://github.com/openai/openai-agents-python)
- [OpenAI Agents SDK - Agents](https://openai.github.io/openai-agents-python/agents/)
- [OpenAI Agents SDK - Running Agents](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI Agents SDK - Tools](https://openai.github.io/openai-agents-python/tools/)
- [OpenAI Agents SDK - Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [OpenAI Agents SDK - Guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenAI Agents SDK - Tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenAI Agents SDK - MCP](https://openai.github.io/openai-agents-python/mcp/)
- [OpenAI Agents SDK - Sessions](https://openai.github.io/openai-agents-python/sessions/)
- [OpenAI Agents SDK - Models](https://openai.github.io/openai-agents-python/models/)
- [OpenAI Agents SDK - Runner Reference](https://openai.github.io/openai-agents-python/ref/run/)
- [OpenAI Agents SDK - RunContext Reference](https://openai.github.io/openai-agents-python/ref/run_context/)
- [OpenAI Agents SDK - Lifecycle Reference](https://openai.github.io/openai-agents-python/ref/lifecycle/)
- [GitHub: openai/swarm](https://github.com/openai/swarm) (predecessor)
- [OpenAI: New tools for building agents](https://openai.com/index/new-tools-for-building-agents/)
- [OpenAI Agents SDK on PyPI](https://pypi.org/project/openai-agents/)
