# Pydantic AI Agent Loop Architecture

## 1. Overview

**Pydantic AI** is a Python agent framework created by the Pydantic team (Samuel Colvin, David Montague, and contributors). It is designed for building production-grade applications with generative AI, emphasizing type safety and ergonomic patterns inspired by FastAPI.

| Property | Value |
|----------|-------|
| **Language** | Python (>=3.10) |
| **Repository** | https://github.com/pydantic/pydantic-ai |
| **Documentation** | https://ai.pydantic.dev/ |
| **License** | MIT |
| **Latest version** | 1.63.0 (Feb 23, 2026) |
| **PyPI** | https://pypi.org/project/pydantic-ai/ |
| **Stars** | 15,000+ |

### Core philosophy

1. **Type safety first.** The `Agent` class is generic (`Agent[DepsType, OutputType]`), giving IDEs and type checkers full visibility into dependency types, tool parameter types, and output types. The goal is to move entire classes of errors from runtime to write-time.
2. **Model-agnostic.** A single agent definition is portable across LLM providers (OpenAI, Anthropic, Gemini, Groq, Ollama, etc.) by swapping only the model identifier string.
3. **Dependency injection.** A FastAPI-inspired `RunContext[DepsType]` system threads typed dependencies through system prompts, tools, and validators.
4. **Production readiness.** Built-in OpenTelemetry tracing (via Pydantic Logfire), usage limits, concurrency controls, fallback models, and structured error capture.
5. **Pydantic-native validation.** Output schemas, tool parameter schemas, and result validation all use Pydantic models and JSON Schema natively.

### Tech stack and key dependencies

- **pydantic** (core validation)
- **pydantic-graph** (finite state machine powering the agent loop)
- **griffe** (function introspection for automatic tool schema generation)
- **httpx** (HTTP transport for model providers)
- **opentelemetry** (observability)
- Optional provider SDKs: `openai`, `anthropic`, `google-genai`, `cohere`, `mistralai`, etc.

### Repository structure

```
pydantic-ai/
  pydantic_ai_slim/        # Core library (lightweight package)
    pydantic_ai/
      agent/                # Agent class, run methods
      _agent_graph.py       # State machine nodes (UserPromptNode, ModelRequestNode, CallToolsNode)
      models/               # Model implementations (openai.py, anthropic.py, gemini.py, ...)
      tools.py              # Tool registration and execution
      output.py             # Output type handling
      result.py             # RunResult, StreamedRunResult
      messages.py           # ModelRequest, ModelResponse, message parts
  pydantic_graph/           # Generic graph/FSM library
  pydantic_evals/           # Evaluation framework
  examples/                 # Usage demonstrations
  docs/                     # Documentation source (Markdown)
```

---

## 2. Agent loop lifecycle

### Entry points

Pydantic AI provides multiple ways to run an agent:

| Method | Sync/Async | Returns |
|--------|-----------|---------|
| `agent.run(prompt, ...)` | async | `AgentRunResult[OutputType]` |
| `agent.run_sync(prompt, ...)` | sync (wraps `loop.run_until_complete`) | `AgentRunResult[OutputType]` |
| `agent.run_stream(prompt, ...)` | async context manager | `StreamedRunResult[OutputType]` |
| `agent.run_stream_sync(prompt, ...)` | sync context manager | `StreamedRunResultSync[OutputType]` |
| `agent.run_stream_events(prompt, ...)` | async iterable | `AgentStreamEvent` / `AgentRunResultEvent` |
| `agent.iter(prompt, ...)` | async context manager | `AgentRun` (node-by-node iteration) |

### The state machine

Under the hood, every run creates an `AgentRun` object powered by `pydantic-graph`. The execution proceeds through a finite state machine with three primary node types and a terminal:

```
UserPromptNode  -->  ModelRequestNode  -->  CallToolsNode
                           ^                     |
                           |                     |
                           +---------------------+
                                (tool results)

                     CallToolsNode  -->  End
                         (no tool calls / final output validated)
```

#### Node responsibilities

1. **UserPromptNode** — The entry point. Collects and formats:
   - Static system prompts (from constructor `system_prompt` / `instructions` parameters)
   - Dynamic system prompts (from `@agent.system_prompt`-decorated functions, which receive `RunContext`)
   - The user prompt string
   - Any `message_history` from prior runs
   - Runtime `instructions` passed to the run call

2. **ModelRequestNode** — Sends accumulated messages to the LLM:
   - Assembles a `ModelRequest` containing all message parts
   - Includes tool definitions (JSON schemas) and output schema
   - Applies merged `ModelSettings` (model defaults < agent defaults < runtime overrides)
   - Calls the model (streaming or non-streaming)
   - Receives a `ModelResponse` containing `TextPart`, `ToolCallPart`, and/or `ThinkingPart` objects
   - Checks usage limits (`UsageLimits.request_limit`, `response_tokens_limit`)

3. **CallToolsNode** — Processes the model's response:
   - If the response contains **tool calls**: validates arguments against schemas, executes tool functions, collects `ToolReturnPart` results, appends them to message history, transitions back to `ModelRequestNode`
   - If the response contains a **final output** (either plain text or structured data via tool-based output): validates against `output_type` schema, runs `@agent.output_validator` functions, and if valid, transitions to `End`
   - If validation fails: sends a `RetryPromptPart` back to the model (up to `retries` limit), transitions back to `ModelRequestNode`
   - Checks `UsageLimits.tool_calls_limit`

4. **End** — Terminal node. The framework creates an `AgentRunResult` containing:
   - `output`: the validated output (typed as `OutputType`)
   - Message history (accessible via `all_messages()` and `new_messages()`)
   - Usage statistics and cost information

### Retry logic

Retries operate at two levels:

- **Tool-level retries.** Each tool has a `retries` count (default: 1, configurable per-tool or agent-wide). When a tool call fails validation or raises `ModelRetry`, the error is sent back to the model as a `RetryPromptPart`. The current retry count is available in `RunContext.retry`.
- **Output validation retries.** When the final output fails Pydantic validation or a `@agent.output_validator` raises `ModelRetry`, the validation error is sent back to the model. Controlled by `output_retries` or the agent-level `retries` parameter.

Both retry mechanisms send the error details back to the LLM so it can self-correct, rather than silently retrying.

### Usage limits

```python
from pydantic_ai import UsageLimits

result = agent.run_sync(
    'prompt',
    usage_limits=UsageLimits(
        response_tokens_limit=500,
        request_limit=10,
        tool_calls_limit=5,
    )
)
```

If any limit is exceeded, `UsageLimitExceeded` is raised.

---

## 3. Agent definition

### The Agent class

```python
from pydantic_ai import Agent

agent = Agent(
    model='openai:gpt-5.2',           # Model identifier string or Model instance
    deps_type=MyDeps,                   # Type for dependency injection
    output_type=MyOutputModel,          # Expected output type (Pydantic model, scalar, union, etc.)
    system_prompt='You are helpful.',    # Static system prompt string
    instructions='Follow these rules.', # Static instructions (always re-injected, even with message_history)
    model_settings=ModelSettings(...),  # Default model settings
    retries=3,                          # Default retry count
    tools=[tool_fn1, tool_fn2],         # Tools registered via constructor
    max_concurrency=10,                 # Concurrency limit
    tool_timeout=30,                    # Default tool execution timeout (seconds)
    history_processors=[fn],            # Functions to transform message history before model calls
    end_strategy='early',              # 'early' or 'exhaustive'
)
```

The Agent class is generic: `Agent[AgentDepsT, OutputDataT]`. Static type checkers (mypy, Pyright) verify that tool parameter types match `deps_type`, output assignments match `output_type`, and system prompt functions receive the correct dependency type.

### System prompts

**Static** — passed as a string to the constructor:

```python
agent = Agent('openai:gpt-5.2', system_prompt='Be concise and accurate.')
```

**Dynamic** — decorated functions that receive `RunContext` and return a string. These are called at the start of each run, allowing prompts to incorporate runtime dependencies:

```python
@agent.system_prompt
async def add_context(ctx: RunContext[MyDeps]) -> str:
    user = await ctx.deps.db.get_user(ctx.deps.user_id)
    return f"The current user is {user.name}, role: {user.role}."
```

Multiple system prompt functions can be registered; all are concatenated.

**Instructions vs. system_prompt**: The key difference is that `instructions` are always re-injected even when `message_history` is provided from a prior run, whereas `system_prompt` content from previous runs is already in the history and not duplicated.

### Dependency injection

Dependencies are defined as any Python type (typically a dataclass) and passed at runtime:

```python
@dataclass
class MyDeps:
    api_key: str
    http_client: httpx.AsyncClient
    db: Database

# At runtime:
result = await agent.run('prompt', deps=MyDeps(api_key='...', http_client=client, db=db))
```

The `RunContext[MyDeps]` object is threaded through:
- System prompt functions
- Tool functions (decorated with `@agent.tool`)
- Output validators
- Tool preparation functions

For testing, use `agent.override(deps=mock_deps)` as a context manager to substitute dependencies without changing application code.

---

## 4. Tool system

### Registration methods

**Decorator with context:**

```python
@agent.tool
async def search_database(ctx: RunContext[MyDeps], query: str, limit: int = 10) -> str:
    """Search the database for records matching the query."""
    results = await ctx.deps.db.search(query, limit=limit)
    return json.dumps(results)
```

**Decorator without context:**

```python
@agent.tool_plain
def roll_dice(sides: int = 6) -> str:
    """Roll a die with the given number of sides."""
    return str(random.randint(1, sides))
```

**Constructor registration:**

```python
from pydantic_ai import Tool

agent = Agent(
    'openai:gpt-5.2',
    tools=[
        roll_dice,                                    # auto-detected
        Tool(search_database, takes_ctx=True),        # explicit
        Tool(roll_dice, takes_ctx=False, retries=3),  # with config
    ]
)
```

### Schema generation

Pydantic AI uses **griffe** for function introspection to automatically generate JSON schemas from:
- Function signatures and parameter type annotations
- Default values
- Docstrings (Google, NumPy, and Sphinx formats supported) for parameter descriptions

The resulting `ToolDefinition` object contains `name`, `description`, and `parameters_json_schema`.

### How the model calls tools

1. The model receives tool definitions as part of the request.
2. If the model decides to call a tool, it returns a `ToolCallPart` in its response with the tool name and JSON arguments.
3. `CallToolsNode` validates the arguments against the tool's Pydantic-generated schema.
4. If validation passes, the tool function is executed.
5. The return value is serialized to JSON as a `ToolReturnPart`.
6. The tool result is appended to message history and sent back to the model in the next `ModelRequestNode` iteration.

### Tool execution modes

- **Parallel** (default): Multiple tool calls execute concurrently via `asyncio.gather()`
- **Sequential**: Tools execute one at a time (`sequential=True` on the tool, or via context manager)
- **Parallel ordered events**: Concurrent execution but events emitted in original call order

```python
# Force sequential execution for a specific run
with agent.parallel_tool_call_execution_mode('sequential'):
    result = agent.run_sync('prompt')
```

### Retries on validation failure

When tool argument validation fails or a tool raises `ModelRetry`:
1. The error message is packaged as a `RetryPromptPart`
2. This is sent back to the model as part of the next request
3. The model can self-correct its arguments
4. Retry count is tracked per-tool in `RunContext.retries` (a dict mapping tool names to attempt counts)
5. After exceeding the retry limit, the error propagates

```python
from pydantic_ai import ModelRetry

@agent.tool(retries=3)
def get_user(ctx: RunContext[MyDeps], username: str) -> dict:
    """Look up a user by their username."""
    user = ctx.deps.db.find_user(username)
    if not user:
        raise ModelRetry(f'No user "{username}" found. Try the full name instead.')
    return user.to_dict()
```

### Dynamic tool preparation

The `prepare` function can modify or omit a tool definition per run step:

```python
async def only_for_admins(ctx: RunContext[MyDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if ctx.deps.user_role != 'admin':
        return None  # Hide this tool from the model
    return tool_def

@agent.tool(prepare=only_for_admins)
def delete_records(ctx: RunContext[MyDeps], record_ids: list[int]) -> str:
    ...
```

### Tool timeouts

```python
agent = Agent('openai:gpt-5.2', tool_timeout=30)  # Agent-wide default

@agent.tool_plain(timeout=5)  # Per-tool override
async def fast_lookup(key: str) -> str:
    ...
```

Timeouts trigger retry prompts that count toward the retry limit.

### Custom argument validation

```python
def validate_sum_limit(ctx: RunContext[int], x: int, y: int) -> None:
    if x + y > ctx.deps:
        raise ModelRetry(f'Sum must not exceed {ctx.deps}')

@agent.tool(args_validator=validate_sum_limit)
def add_numbers(ctx: RunContext[int], x: int, y: int) -> int:
    return x + y
```

---

## 5. Result handling

### Output type system

The `output_type` parameter (formerly `result_type`) controls what the agent returns. Supported types:

| Type | Behavior |
|------|----------|
| `str` (default) | Plain text output |
| Pydantic `BaseModel` | Structured output validated by Pydantic |
| `dataclass`, `TypedDict` | Structured output |
| Scalar (`int`, `float`, `bool`) | Wrapped in single-element object schema |
| Union of types | Each type registers as a separate output tool |
| List of types | Same as union |
| Output functions | Functions called with model-provided arguments |
| `BinaryImage` | Image generation output |

### Output modes

**1. Tool Output (default):** The output schema is presented to the model as a tool. The model "calls" this tool to produce its final answer. Supports multiple output types via union.

```python
from pydantic_ai import Agent, ToolOutput
from pydantic import BaseModel

class CityInfo(BaseModel):
    name: str
    population: int
    country: str

agent = Agent('openai:gpt-5.2', output_type=CityInfo)
result = agent.run_sync('Tell me about Paris')
# result.output is typed as CityInfo
```

With multiple outputs:

```python
agent = Agent(
    'openai:gpt-5.2',
    output_type=[
        ToolOutput(CityInfo, name='return_city'),
        ToolOutput(str, name='return_text'),
    ],
)
```

**2. Native Output:** Uses the model's built-in "Structured Outputs" / JSON Schema response format:

```python
from pydantic_ai import NativeOutput

agent = Agent('openai:gpt-5.2', output_type=NativeOutput(CityInfo))
```

Limitation: Not all models support this. Gemini cannot use tools and native structured output simultaneously.

**3. Prompted Output:** Injects the schema into the system prompt and parses the model's text response:

```python
from pydantic_ai import PromptedOutput

agent = Agent(
    'openai:gpt-5.2',
    output_type=PromptedOutput(CityInfo, template='Return JSON matching: {schema}'),
)
```

Least reliable but works with all models. Enables JSON Mode when the model supports it.

### End strategy

When multiple output tools are available and the model calls several in parallel:
- `'early'` (default): Stops after the first valid output is found
- `'exhaustive'`: Executes all output tool calls; first valid output wins

### Output validation

Pydantic validates the model's output automatically against the declared schema. Additionally, custom validators can be registered:

```python
@agent.output_validator
async def validate_output(ctx: RunContext[MyDeps], output: CityInfo) -> CityInfo:
    if output.population < 0:
        raise ModelRetry('Population cannot be negative')
    return output
```

Validation context can be passed for Pydantic field validators:

```python
agent = Agent(
    'openai:gpt-5.2',
    output_type=Value,
    validation_context=10,  # Static context
)

# Or dynamic, derived from deps:
agent = Agent(
    'openai:gpt-5.2',
    output_type=Value,
    deps_type=MyDeps,
    validation_context=lambda ctx: ctx.deps.some_value,
)
```

### Output functions

Instead of returning structured data directly, you can specify functions that are called with model-provided arguments:

```python
def run_sql_query(query: str) -> list[dict]:
    """Execute a SQL query and return results."""
    return execute_sql(query)

agent = Agent('openai:gpt-5.2', output_type=[run_sql_query])
```

Output functions can accept `RunContext` as their first parameter and can raise `ModelRetry`.

### Custom JSON schemas via StructuredDict

For externally-defined or dynamic schemas:

```python
from pydantic_ai import StructuredDict

PersonDict = StructuredDict(
    {'type': 'object', 'properties': {'name': {'type': 'string'}, 'age': {'type': 'integer'}}, 'required': ['name', 'age']},
    name='Person',
)
agent = Agent('openai:gpt-5.2', output_type=PersonDict)
result = agent.run_sync('Create a person')
# result.output is a dict
```

---

## 6. Model abstraction

### Core abstractions

Pydantic AI defines three layers:

1. **Model** — Wraps vendor-specific SDKs behind a unified API. Named `<VendorSdk>Model` (e.g., `OpenAIChatModel`, `AnthropicModel`, `GeminiModel`).
2. **Provider** — Handles authentication and connection to specific endpoints. Enables custom providers for API-compatible services, gateways, or alternative auth.
3. **Profile** — Describes how to construct requests for optimal results across model families (e.g., different JSON schema restrictions for tools).

### Supported implementations

Built-in model classes:
- `OpenAIChatModel` (OpenAI)
- `AnthropicModel` (Anthropic)
- `GeminiModel` (Google Gemini via Generative Language API)
- `VertexAIModel` (Google Vertex AI)
- `BedrockConverseModel` (Amazon Bedrock)
- `GroqModel` (Groq)
- `MistralModel` (Mistral)
- `CohereModel` (Cohere)
- `HuggingFaceModel` (Hugging Face)
- `XAIModel` (xAI/Grok)
- `OpenRouterModel` (OpenRouter)
- `TestModel` / `FunctionModel` (testing/development)

OpenAI-compatible services using `OpenAIChatModel` with custom providers:
- Ollama, DeepSeek, Azure AI, Together AI, Fireworks AI, LiteLLM, Perplexity, GitHub Models, Alibaba DashScope, Vercel AI Gateway

### Model identifiers

Agents accept shorthand strings: `"<provider>:<model_name>"`:

```python
agent = Agent('openai:gpt-5.2')
agent = Agent('anthropic:claude-sonnet-4-5')
agent = Agent('google-gla:gemini-3-flash-preview')
agent = Agent('groq:llama-3.3-70b-versatile')
```

Pydantic AI auto-selects the appropriate model class, provider, and profile.

### ModelSettings

Settings are merged in priority order: model defaults < agent defaults < runtime overrides.

```python
from pydantic_ai import ModelSettings

agent = Agent(
    'openai:gpt-5.2',
    model_settings=ModelSettings(temperature=0.5, max_tokens=1000),
)

# Runtime override wins:
result = agent.run_sync('prompt', model_settings=ModelSettings(temperature=0.0))
```

### Fallback models

```python
from pydantic_ai.models.fallback import FallbackModel

fallback = FallbackModel(
    OpenAIChatModel('gpt-4o'),
    AnthropicModel('claude-sonnet-4-5'),
)
agent = Agent(fallback)
```

Automatically switches to the next model on 4xx/5xx HTTP errors.

### Concurrency-limited models

```python
from pydantic_ai import ConcurrencyLimitedModel, ConcurrencyLimiter

# Per-model limit
model = ConcurrencyLimitedModel('openai:gpt-4o', limiter=5)

# Shared limit across models
shared = ConcurrencyLimiter(max_running=10, name='openai-pool')
model1 = ConcurrencyLimitedModel('openai:gpt-4o', limiter=shared)
model2 = ConcurrencyLimitedModel('openai:gpt-4o-mini', limiter=shared)
```

### Custom model implementation

Subclass the `Model` abstract base class. For streaming, also implement `StreamedResponse`. Existing implementations (e.g., `OpenAIChatModel`) serve as reference. OpenAI-compatible APIs typically only need a custom provider, not a new model class.

---

## 7. Streaming

### run_stream()

The primary streaming API returns a context manager:

```python
async with agent.run_stream('Tell me about whales') as result:
    # Stream text (accumulated mode, default)
    async for text in result.stream_text():
        print(text)  # Growing string: "Whales", "Whales are", "Whales are mammals", ...

    # Stream text (delta mode)
    async for delta in result.stream_text(delta=True):
        print(delta)  # Just new chunks: "Whales", " are", " mammals", ...
```

### Streaming structured output

```python
async with agent.run_stream('Create a user profile') as result:
    async for partial_profile in result.stream_output():
        print(partial_profile)  # Partial UserProfile objects as data arrives
```

### Debouncing

The `debounce_by` parameter (default: 0.1 seconds) groups rapid streaming events to reduce validation and processing overhead:

```python
async with agent.run_stream('prompt') as result:
    async for text in result.stream_text(debounce_by=0.05):
        ...
    # Or disable debouncing entirely:
    async for text in result.stream_text(debounce_by=None):
        ...
```

### Internal streaming architecture

- **StreamedResponse** abstract class provides a uniform interface across providers
- **ModelResponsePartsManager** assembles deltas into complete parts:
  - `handle_text_delta()` — accumulates text
  - `handle_tool_call_delta()` — streams tool call arguments
  - `handle_thinking_delta()` — streams reasoning content
- Event types: `PartStartEvent`, `PartDeltaEvent`, `PartEndEvent`, `FinalResultEvent`
- Response detection: Pydantic AI streams enough of the response to determine whether it is a tool call or final output, then either executes tools (looping back) or returns the stream as a `StreamedRunResult`

### Streaming with tool calls

During a streamed run, the agent loop still executes tool calls normally. The streaming only applies to the final text/structured output. Tool calls are processed in `CallToolsNode` between model requests, and the stream resumes when the model produces its final response.

### run_stream_events()

For maximum control, stream individual execution events:

```python
async for event in agent.run_stream_events('prompt'):
    if isinstance(event, AgentStreamEvent):
        ...  # Intermediate events (tool calls, partial text)
    elif isinstance(event, AgentRunResultEvent):
        ...  # Final result
```

### Partial output handling in output functions

During streaming, output functions and validators may be called multiple times. Use `RunContext.partial_output` to guard side effects:

```python
def save_record(ctx: RunContext, record: Record) -> Record:
    if ctx.partial_output:
        return record  # Skip side effects during partial streaming
    db.save(record)    # Only execute on final output
    return record
```

---

## 8. Message history

### Internal representation

Messages are stored as a list of `ModelRequest` and `ModelResponse` objects:

**ModelRequest** contains:
- `parts`: list of message components (`UserPromptPart`, `ToolReturnPart`, `RetryPromptPart`, etc.)
- `timestamp`: when the request was created
- `instructions`: system instructions for that run
- `run_id`: identifier linking messages to their run

**ModelResponse** contains:
- `parts`: response components (`TextPart`, `ToolCallPart`, `ThinkingPart`)
- `usage`: token counts (input/output)
- `model_name`: which model generated the response
- `timestamp` and `run_id`

### Accessing messages

```python
result = agent.run_sync('Tell me a joke')

# All messages (including any provided message_history)
all_msgs = result.all_messages()

# Only messages from this run
new_msgs = result.new_messages()

# JSON serialized variants
all_json = result.all_messages_json()
new_json = result.new_messages_json()
```

### Continuing conversations

Pass previous messages via `message_history`:

```python
result1 = agent.run_sync('Tell me a joke')
result2 = agent.run_sync(
    'Explain why that is funny',
    message_history=result1.new_messages(),
)
```

When `message_history` is provided, a new system prompt is not generated from the `system_prompt` parameter (it is assumed to be in the history). However, `instructions` are always re-injected.

### Serialization for persistence

```python
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python, to_json

history = result.all_messages()

# To Python objects (for database storage)
python_objects = to_jsonable_python(history)
restored = ModelMessagesTypeAdapter.validate_python(python_objects)

# To JSON bytes
json_data = to_json(history)
restored = ModelMessagesTypeAdapter.validate_json(json_data)
```

### History processors

Transform message history before each model request (for context window management, etc.):

```python
def keep_recent(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Keep only the 5 most recent messages."""
    return messages[-5:] if len(messages) > 5 else messages

agent = Agent('openai:gpt-4o', history_processors=[keep_recent])
```

Processors can be sync or async, and can receive `RunContext` for context-aware filtering.

### Cross-model compatibility

Message history is model-agnostic. You can start a conversation with one provider and continue with another:

```python
result1 = agent.run_sync('Tell me a joke')  # Uses OpenAI
result2 = agent.run_sync(
    'Explain it',
    model='anthropic:claude-sonnet-4-5',
    message_history=result1.new_messages(),
)
```

---

## 9. Comparison notes — Pydantic AI vs. minimal custom agent loop

### Strengths of Pydantic AI

1. **Rich type safety.** The generic `Agent[DepsT, OutputT]` propagates types through tools, validators, and results. A minimal loop typically has `Any`-typed tool returns and untyped message dicts.

2. **Structured output as a first-class concept.** Three output modes (Tool, Native, Prompted), automatic Pydantic validation, and retry-on-failure. A minimal loop usually treats output as raw text or requires manual JSON parsing and validation.

3. **Automatic tool schema generation.** Functions become tools with zero boilerplate — signatures, type hints, and docstrings are automatically converted to JSON schemas via griffe. A minimal loop requires manually writing tool definitions.

4. **Self-correcting retries.** Validation errors and `ModelRetry` exceptions are sent back to the model as structured error messages, giving it a chance to fix its response. A minimal loop typically either crashes or retries blindly.

5. **Model portability.** Swapping from OpenAI to Anthropic to Gemini is a one-line change. A minimal loop is typically tightly coupled to one provider's SDK.

6. **Dependency injection.** Clean separation of configuration, secrets, and services from agent logic. Makes testing straightforward with `agent.override()`. A minimal loop threads dependencies ad-hoc.

7. **Built-in observability.** OpenTelemetry spans for every run, model request, and tool call. A minimal loop requires manual instrumentation.

8. **Production features.** Usage limits, concurrency controls, fallback models, tool timeouts, history processors. These take significant effort to build from scratch.

9. **Streaming architecture.** Unified streaming across providers with debouncing, partial validation, and delta/accumulated modes. A minimal loop typically has provider-specific streaming or none at all.

10. **Multi-agent patterns.** Agents can call other agents as tools, enabling delegation patterns. Documentation covers agent-as-tool and handoff patterns.

### Weaknesses / trade-offs of Pydantic AI

1. **Abstraction overhead.** The state machine (pydantic-graph), three output modes, multiple run methods, generic types, and provider abstraction layers create significant conceptual overhead. A minimal loop is immediately understandable: assemble messages, call API, handle tool calls, repeat.

2. **Opaque internals.** The graph-based execution makes it harder to debug exactly what happens between steps. A minimal loop's control flow is explicit in a single function.

3. **Dependency weight.** Requires pydantic, pydantic-graph, griffe, and provider SDKs. A minimal loop can operate with just `httpx` and the raw API.

4. **Learning curve.** Understanding `RunContext`, `ToolOutput` vs `NativeOutput` vs `PromptedOutput`, `end_strategy`, `history_processors`, the generic type system, and the decorator-based registration requires reading substantial documentation. A minimal loop's entire API surface fits in one file.

5. **Framework lock-in.** Tools, prompts, and output types are defined using Pydantic AI's decorator and class patterns. Migrating to a different framework requires rewriting these. A minimal loop's tool functions are plain functions that can be reused anywhere.

6. **Async-first design.** Even `run_sync()` internally wraps an async event loop. This can cause issues in already-running event loops or in environments where async is undesirable. A minimal loop can be purely synchronous.

7. **Less control over message assembly.** The framework controls how messages are assembled, when system prompts are injected, and how tool results are formatted. A minimal loop gives full control over the exact prompt structure sent to the model.

8. **Rapid evolution.** At version 1.63.0 with frequent releases, the API surface has changed significantly (e.g., `result_type` renamed to `output_type`, new output modes added). A minimal loop's API is whatever you define it to be.

### Key architectural differences

| Aspect | Pydantic AI | Minimal custom loop |
|--------|-------------|---------------------|
| Loop control | Implicit (graph state machine) | Explicit (while loop) |
| Tool definitions | Auto-generated from functions | Manually specified JSON schemas |
| Output validation | Automatic with retry | Manual or absent |
| Provider abstraction | Full abstraction layer | Direct SDK calls |
| Type safety | Generic types throughout | Ad-hoc typing |
| Message format | `ModelRequest`/`ModelResponse` with typed parts | Provider-specific dicts |
| Configuration | Decorators + constructor params | Config file/dict |
| Testability | `override()`, `TestModel`, `FunctionModel` | Mock the HTTP client |
| Code size | ~thousands of lines across packages | ~hundreds of lines |
| Debugging | Requires understanding graph execution | Read the loop function |

---

## Sources

- [Pydantic AI Documentation — Home](https://ai.pydantic.dev/)
- [Pydantic AI — Agents](https://ai.pydantic.dev/agent/)
- [Pydantic AI — Function Tools](https://ai.pydantic.dev/tools/)
- [Pydantic AI — Advanced Tool Features](https://ai.pydantic.dev/tools-advanced/)
- [Pydantic AI — Output](https://ai.pydantic.dev/output/)
- [Pydantic AI — Dependencies](https://ai.pydantic.dev/dependencies/)
- [Pydantic AI — Models Overview](https://ai.pydantic.dev/models/overview/)
- [Pydantic AI — Message History](https://ai.pydantic.dev/message-history/)
- [Pydantic AI — Agent API Reference](https://ai.pydantic.dev/api/agent/)
- [Pydantic AI — Output API Reference](https://ai.pydantic.dev/api/output/)
- [GitHub — pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai)
- [PyPI — pydantic-ai](https://pypi.org/project/pydantic-ai/)
- [DeepWiki — Agent Run Lifecycle](https://deepwiki.com/pydantic/pydantic-ai/2.1-agent-run-lifecycle)
- [DeepWiki — Tools System / Execution Flow](https://deepwiki.com/pydantic/pydantic-ai/2.2-tools-system)
- [DeepWiki — Streaming and Real-time Processing](https://deepwiki.com/pydantic/pydantic-ai/4.1-streaming-and-real-time-processing)
