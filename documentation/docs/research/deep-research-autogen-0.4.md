# AutoGen 0.4 (AgentChat) Architecture Research

## 1. Overview

### What is AutoGen 0.4?

AutoGen 0.4 is Microsoft's **complete from-scratch rewrite** of the AutoGen multi-agent conversation framework. It is a programming framework for creating multi-agent AI applications that can act autonomously or work alongside humans. The rewrite was driven by customer and community feedback demanding better observability, flexibility, scalability, and interactive control.

- **Repo**: [microsoft/autogen](https://github.com/microsoft/autogen)
- **License**: MIT (code), CC-BY-4.0 (documentation)
- **Language**: Python (primary), .NET (secondary), with Protocol Buffer definitions for cross-language interop
- **Docs**: https://microsoft.github.io/autogen/stable/
- **PyPI packages**: `autogen-core`, `autogen-agentchat`, `autogen-ext`, `autogenstudio`

### Core Philosophy

AutoGen 0.4 adopts the **actor model of computing** to support distributed, event-driven, scalable agent systems. Agents communicate through asynchronous messages (both event-driven and request/response patterns). The framework enforces full type support with interfaces and extensive typing throughout, and provides a pluggable, modular architecture for custom agents, tools, memory, and models.

### Three-Layer Architecture

```
┌─────────────────────────────────────────────────┐
│  AgentChat API (High-Level, Task-Driven)        │
│  AssistantAgent, Teams, Termination, Memory      │
├─────────────────────────────────────────────────┤
│  Core API (Foundation, Event-Driven Actor Model) │
│  RoutedAgent, Runtime, Topics, Subscriptions     │
├─────────────────────────────────────────────────┤
│  Extensions (3rd Party, Integrations)            │
│  OpenAI client, Docker executor, MCP, ChromaDB   │
└─────────────────────────────────────────────────┘
```

1. **Core API (`autogen-core`)**: Foundation layer. Scalable, event-driven actor framework. Provides `RoutedAgent`, `SingleThreadedAgentRuntime`, message passing, topics, and subscriptions. Low-level building blocks for advanced users.
2. **AgentChat API (`autogen-agentchat`)**: High-level, task-driven API built on Core. Provides `AssistantAgent`, team orchestrators (`RoundRobinGroupChat`, `SelectorGroupChat`, `Swarm`, `GraphFlow`), termination conditions, memory, and state management. Most similar to AutoGen 0.2 and the primary migration target.
3. **Extensions (`autogen-ext`)**: Implementations of core interfaces that depend on external services: `OpenAIChatCompletionClient`, `AzureOpenAIChatCompletionClient`, Docker-based code executors, MCP integration, ChromaDB memory, LangChain tool adapters, etc.

### How It Differs from AutoGen 0.2

| Aspect | AutoGen 0.2 | AutoGen 0.4 |
|--------|-------------|-------------|
| Architecture | Synchronous, chat-centric | Asynchronous, event-driven actor model |
| Scalability | Single-process, not scalable | Distributed runtime across processes/machines |
| Modularity | Monolithic `ConversableAgent` | Layered (Core + AgentChat + Extensions) |
| Type safety | Loose typing | Full type enforcement with interfaces |
| Observability | Minimal | OpenTelemetry tracing built-in |
| Cross-language | Python only | Python + .NET + protobuf interop |
| State management | Implicit | Explicit `save_state()`/`load_state()` |
| Memory | Ad hoc | First-class `Memory` protocol with backends |

**Note on the AG2 fork**: The original founding contributors of AutoGen 0.2 forked the project as [AG2](https://github.com/ag2ai/ag2) (formerly AutoGen 0.2.34, now AG2 0.3.x) under a separate organization with open governance. Microsoft's AutoGen 0.4 is the official Microsoft continuation, a complete rewrite rather than an evolution of 0.2.

---

## 2. Agent Loop Lifecycle

The heart of AutoGen 0.4 is how a single agent turn processes messages, calls the LLM, executes tools, and produces a response. The `AssistantAgent.on_messages_stream()` method implements this loop.

### Step-by-Step Lifecycle

```
┌──────────────────────────────────────────────┐
│ 1. Receive messages (on_messages / run)       │
│    - Add new messages to model_context        │
│    - Extract HandoffMessage contexts          │
├──────────────────────────────────────────────┤
│ 2. Update memory                              │
│    - Query memory stores for relevant content │
│    - Yield MemoryQueryEvent                   │
├──────────────────────────────────────────────┤
│ 3. Call LLM (_call_llm)                       │
│    - system_message + context messages        │
│    - Include tool schemas + handoff tools     │
│    - Optional streaming mode                  │
├──────────────────────────────────────────────┤
│ 4. Tool call loop (up to max_tool_iterations) │
│    ┌─────────────────────────────────────┐    │
│    │ If model returns text → final resp  │    │
│    │ If model returns tool calls:        │    │
│    │   - Yield ToolCallRequestEvent      │    │
│    │   - Execute tools concurrently      │    │
│    │   - Yield ToolCallExecutionEvent    │    │
│    │   - Check for handoff triggers      │    │
│    │   - If not last iter → call LLM     │    │
│    │     again with tool results         │    │
│    └─────────────────────────────────────┘    │
├──────────────────────────────────────────────┤
│ 5. Final response                             │
│    - If reflect_on_tool_use=True:             │
│      Call LLM again without tools → TextMsg   │
│    - If reflect_on_tool_use=False:            │
│      Format tool results → ToolCallSummaryMsg │
└──────────────────────────────────────────────┘
```

### Key Methods

```python
# The synchronous entry point delegates to streaming:
async def on_messages(
    self,
    messages: Sequence[BaseChatMessage],
    cancellation_token: CancellationToken,
) -> Response:
    async for message in self.on_messages_stream(messages, cancellation_token):
        if isinstance(message, Response):
            return message
    raise AssertionError("The stream should have returned the final result.")
```

The `on_messages_stream` method is an `AsyncGenerator` that yields intermediate events (`ToolCallRequestEvent`, `ToolCallExecutionEvent`, `MemoryQueryEvent`) and finally a `Response` object containing:
- `chat_message`: The final `TextMessage`, `StructuredMessage`, `HandoffMessage`, or `ToolCallSummaryMessage`
- `inner_messages`: List of all intermediate processing events

### Important Agent Design Principle

Agents are **stateful**. The framework documentation states: "Agents are expected to be stateful and this method is expected to be called with new messages, not complete history." The model context accumulates messages across calls; callers should only pass new messages, not the full history.

---

## 3. Agent Types

### BaseChatAgent (Abstract Base)

All AgentChat agents inherit from `BaseChatAgent`:

```python
class BaseChatAgent(name: str, description: str):
    # Properties
    name: str                                    # Unique within team
    description: str                             # Describes capabilities
    produced_message_types: Sequence[type[BaseChatMessage]]

    # Core methods
    async on_messages(messages, cancellation_token) -> Response
    async on_messages_stream(messages, cancellation_token) -> AsyncGenerator
    async on_reset(cancellation_token) -> None
    async run(task, cancellation_token=None, output_task_messages=True) -> TaskResult
    async run_stream(task, cancellation_token=None, output_task_messages=True) -> AsyncGenerator
    async save_state() -> Mapping[str, Any]
    async load_state(state: Mapping[str, Any]) -> None
```

### AssistantAgent

The primary "kitchen sink" agent for prototyping:

```python
class AssistantAgent(
    name: str,
    model_client: ChatCompletionClient,
    *,
    tools: List[BaseTool | Callable] | None = None,
    workbench: Workbench | Sequence[Workbench] | None = None,
    handoffs: List[Handoff | str] | None = None,
    model_context: ChatCompletionContext | None = None,
    description: str = "An agent that provides assistance...",
    system_message: str | None = "You are a helpful AI assistant...",
    model_client_stream: bool = False,
    reflect_on_tool_use: bool | None = None,
    max_tool_iterations: int = 1,
    tool_call_summary_format: str = "{result}",
    tool_call_summary_formatter: Callable | None = None,
    output_content_type: type[BaseModel] | None = None,
    output_content_type_format: str | None = None,
    memory: Sequence[Memory] | None = None,
    metadata: Dict[str, str] | None = None,
)
```

Key parameters explained:
- **`tools`**: List of `BaseTool` instances or plain callables. The agent automatically generates JSON schemas from type annotations.
- **`workbench`**: Alternative to `tools`; supports Model Context Protocol (MCP) servers. `McpWorkbench` connects to MCP servers for dynamic tool discovery.
- **`handoffs`**: Agent names or `Handoff` objects for delegation. The model uses tool-calling to generate handoff function calls.
- **`model_context`**: The `ChatCompletionContext` that stores conversation history. Defaults to unbounded if not specified.
- **`reflect_on_tool_use`**: If `True`, after tool execution the agent makes an additional LLM call (without tools) to produce a natural-language summary instead of raw tool output.
- **`max_tool_iterations`**: Controls how many sequential tool-call rounds are allowed per agent turn (default: 1). Set higher (e.g., 5) when the model needs multiple tool calls to reach a goal.
- **`output_content_type`**: A Pydantic `BaseModel` class for structured output. Forces the model to return JSON conforming to the schema.

Produced message types: `TextMessage`, `StructuredMessage`, `HandoffMessage`, `ToolCallSummaryMessage`.

### CodeExecutorAgent

Generates and executes code:

```python
class CodeExecutorAgent(
    name: str,
    code_executor: CodeExecutor,           # e.g., DockerCommandLineCodeExecutor
    *,
    model_client: ChatCompletionClient | None = None,
    model_context: ChatCompletionContext | None = None,
    max_retries_on_error: int = 0,
    sources: Sequence[str] | None = None,  # Limit code extraction to specific agents
    supported_languages: List[str] | None = None,  # Default: ["python", "sh"]
    approval_func: Callable | None = None, # Pre-execution approval callback
)
```

Key methods:
- `extract_code_blocks_from_messages(messages) -> List[CodeBlock]`
- `execute_code_block(code_blocks, cancellation_token) -> CodeResult`

### SocietyOfMindAgent

A meta-agent that orchestrates an inner team and synthesizes their output:

```python
class SocietyOfMindAgent(
    name: str,
    team: Team,                            # Inner team providing expert responses
    model_client: ChatCompletionClient,     # Synthesizer LLM
    *,
    instruction: str = DEFAULT_INSTRUCTION,
    response_prompt: str = DEFAULT_RESPONSE_PROMPT,
    model_context: ChatCompletionContext | None = None,
)
```

This agent runs the inner team, collects all their messages, then uses the synthesizer LLM to produce a single unified response.

### UserProxyAgent (Legacy Concept)

In AutoGen 0.2, `UserProxyAgent` was a core class for human-in-the-loop interaction. In 0.4, this pattern is replaced by:
- `HandoffTermination` + `Swarm` for pausing execution and awaiting user input
- Human-in-the-loop patterns using `ExternalTermination`
- The `approval_func` callback on `CodeExecutorAgent`

### Custom Agents

Subclass `BaseChatAgent` and implement `on_messages` / `on_messages_stream`:

```python
class MyCustomAgent(BaseChatAgent):
    def __init__(self, name: str):
        super().__init__(name, description="My custom agent")

    @property
    def produced_message_types(self):
        return [TextMessage]

    async def on_messages(self, messages, cancellation_token) -> Response:
        # Custom logic here
        return Response(chat_message=TextMessage(content="...", source=self.name))

    async def on_reset(self, cancellation_token) -> None:
        pass
```

---

## 4. Conversation Patterns

AutoGen 0.4 provides four primary multi-agent orchestration patterns, all implemented as "Team" classes.

### RoundRobinGroupChat

Agents take turns in a fixed, deterministic order. Each agent broadcasts its response to all other members.

```python
from autogen_agentchat.teams import RoundRobinGroupChat

team = RoundRobinGroupChat(
    participants=[agent_a, agent_b, agent_c],
    termination_condition=MaxMessageTermination(max_messages=10),
)
result = await team.run(task="Solve this problem")
```

- **Deterministic**: Agent order never changes regardless of content.
- **Resumable**: Calling `run()` again without `reset()` continues from the next agent in rotation.
- **Best for**: Simple, predictable pipelines (e.g., writer then reviewer).

### SelectorGroupChat

A generative model (LLM) selects the next speaker based on the shared context and each agent's description.

```python
from autogen_agentchat.teams import SelectorGroupChat

team = SelectorGroupChat(
    participants=[planner, researcher, analyst],
    model_client=model_client,
    termination_condition=termination,
    selector_prompt="Select an agent...\n{roles}\n{history}\n{participants}",
    allow_repeated_speaker=True,
    selector_func=custom_selector,       # Optional: override LLM selection
    candidate_func=candidate_filter,     # Optional: filter eligible agents
)
```

The `selector_prompt` template supports three variables:
- `{participants}`: Candidate agent names as a JSON list
- `{roles}`: Agent names paired with their descriptions
- `{history}`: Conversation history

Custom functions:
- `selector_func(messages) -> str | None` -- return agent name or `None` to fall back to LLM selection
- `candidate_func(messages) -> List[str]` -- return list of eligible agent names (only works when `selector_func` is not set)

**Best for**: Dynamic, context-aware task routing where different agents have distinct specializations.

### Swarm

Agents hand off tasks to each other using `HandoffMessage` via tool-calling. No central orchestrator; agents make local decisions.

```python
from autogen_agentchat.teams import Swarm

travel_agent = AssistantAgent(
    "travel_agent",
    model_client=model_client,
    handoffs=["flights_agent", "hotels_agent", "user"],
    system_message="You handle travel planning..."
)

team = Swarm(
    participants=[travel_agent, flights_agent, hotels_agent],
    termination_condition=HandoffTermination(target="user") | TextMentionTermination("DONE"),
)
```

- The speaker at each turn is determined by the most recent `HandoffMessage` in the context.
- All agents share the same message context.
- Models supporting parallel tool calls may produce multiple handoffs simultaneously; disable with `parallel_tool_calls=False` on the model client.
- **Best for**: Customer service flows, dynamic delegation, OpenAI Swarm-style patterns.

### GraphFlow

Directed-graph-based orchestration supporting sequential, parallel, conditional, and loop patterns.

```python
from autogen_agentchat.teams import GraphFlow, DiGraphBuilder

builder = DiGraphBuilder()
builder.add_node(writer).add_node(reviewer).add_node(editor)
builder.add_edge(writer, reviewer)
builder.add_edge(reviewer, editor, condition=lambda msg: "APPROVE" in msg.to_model_text())
builder.add_edge(reviewer, writer, condition=lambda msg: "REVISE" in msg.to_model_text())
builder.set_entry_point(writer)

flow = GraphFlow(
    participants=[writer, reviewer, editor],
    graph=builder.build(),
    termination_condition=termination,
)
```

Supported patterns:
- **Sequential**: `A -> B -> C`
- **Parallel fan-out/join**: `A -> [B, C] -> D`
- **Conditional branching**: Edges with `condition=` lambdas
- **Loops**: Cycles with exit conditions
- **Activation groups**: Control when a node with multiple incoming edges fires (`"all"` vs `"any"`)

`MessageFilterAgent` can wrap agents to control which messages they see, reducing noise and hallucinations in complex graphs.

**Best for**: Structured workflows with well-defined branching and looping logic.

### MagenticOneGroupChat

A built-in generalist multi-agent system designed for open-ended web and file-based tasks. Uses a specialized orchestrator agent that manages a web surfer, coder, file surfer, and other agents.

---

## 5. Tool Execution

### Defining Tools

Tools are defined as plain Python functions (sync or async) and wrapped with `FunctionTool`:

```python
from autogen_core.tools import FunctionTool
from typing_extensions import Annotated

async def get_stock_price(
    ticker: str,
    date: Annotated[str, "Date in YYYY/MM/DD format"],
) -> float:
    """Get the stock price for a given ticker on a given date."""
    return 142.50

tool = FunctionTool(get_stock_price, description="Get the stock price.")
```

The `FunctionTool` class:
- Inspects the function signature and type annotations
- Automatically generates a JSON schema for the LLM
- Uses docstrings and `Annotated` descriptions to inform the model

### BaseTool Interface

All tools implement `BaseTool`:

```python
class BaseTool:
    @property
    def schema(self) -> dict:              # JSON schema for tool parameters
    @property
    def name(self) -> str:                 # Tool identifier

    async def run_json(self, args: dict, cancellation_token) -> Any
    def return_value_as_string(self, result: Any) -> str
```

### Schema Example

```json
{
  "name": "get_stock_price",
  "description": "Get the stock price.",
  "parameters": {
    "type": "object",
    "properties": {
      "ticker": {"type": "string"},
      "date": {"type": "string", "description": "Date in YYYY/MM/DD"}
    },
    "required": ["ticker", "date"],
    "additionalProperties": false
  },
  "strict": false
}
```

### Tool Execution Flow

1. **Schema registration**: Tool schemas are passed to the model client alongside the prompt.
2. **Model generates `FunctionCall` objects**: The model returns structured JSON tool calls.
3. **Argument parsing**: `json.loads()` extracts arguments from the JSON string.
4. **Execution**: `run_json(arguments, cancellation_token)` executes the tool. Multiple tool calls execute concurrently via `asyncio.gather()`.
5. **Results wrapped**: Each result becomes a `FunctionExecutionResult`.
6. **Added to context**: Results are added to the model context as `FunctionExecutionResultMessage`.
7. **Reflection or summary**: Depending on `reflect_on_tool_use`, the model either generates a natural-language reflection or the results are formatted via `tool_call_summary_format`.

### Registering Tools with Agents

Tools are passed directly to the `AssistantAgent` constructor:

```python
agent = AssistantAgent(
    name="analyst",
    model_client=model_client,
    tools=[get_stock_price, calculate_returns],  # Plain callables or BaseTool instances
    reflect_on_tool_use=True,
    max_tool_iterations=5,
)
```

### Built-in Tools

- `PythonCodeExecutionTool`: Execute Python snippets
- `HttpTool`: Make REST API requests
- `LocalSearchTool` / `GlobalSearchTool`: GraphRAG integration
- `mcp_server_tools()`: Discover and use tools from MCP servers
- `LangChainToolAdapter`: Wrap LangChain tools for use in AutoGen

### Workbench / MCP Integration

The `Workbench` interface (and `McpWorkbench` implementation) provides an alternative to static tool lists. It connects to Model Context Protocol servers for dynamic tool discovery:

```python
from autogen_ext.tools.mcp import McpWorkbench, SseServerParams

workbench = McpWorkbench(server_params=SseServerParams(url="http://localhost:8080/mcp"))

agent = AssistantAgent(
    name="agent",
    model_client=model_client,
    workbench=workbench,  # Dynamic tool discovery via MCP
)
```

---

## 6. Memory and State

### Model Context (Short-Term / Conversation History)

`ChatCompletionContext` is the base abstraction for managing the message history sent to the LLM. It provides:

```python
class ChatCompletionContext:
    async def add_message(self, message: LLMMessage) -> None
    async def get_messages(self) -> List[LLMMessage]
```

Implementations:
- **`UnboundedChatCompletionContext`**: Stores all messages (default).
- **`BufferedChatCompletionContext`**: MRU buffer keeping only the last `buffer_size` messages.
- **`TokenLimitedChatCompletionContext`**: Truncates based on token count.

```python
from autogen_core.model_context import BufferedChatCompletionContext

agent = AssistantAgent(
    name="agent",
    model_client=model_client,
    model_context=BufferedChatCompletionContext(buffer_size=20),
)
```

The context is the primary mechanism for controlling how much conversation history the model sees. It acts as a sliding window over the full conversation.

### Memory Protocol (Long-Term / Persistent)

The `Memory` protocol defines a pluggable interface for persistent fact stores:

```python
class Memory(Protocol):
    async def add(self, content: MemoryContent) -> None
    async def query(self, query: str, **kwargs) -> List[MemoryContent]
    async def update_context(self, model_context: ChatCompletionContext) -> None
    async def clear(self) -> None
    async def close(self) -> None
```

Memory content uses `MemoryContent` with MIME types:

```python
from autogen_core.memory import MemoryContent, MemoryMimeType

entry = MemoryContent(
    content="User prefers metric units",
    mime_type=MemoryMimeType.TEXT,
    metadata={"category": "preferences"},
)
```

### Memory Backends

1. **`ListMemory`**: Simple chronological list. Appends all stored memories to context.

    ```python
    from autogen_core.memory import ListMemory
    memory = ListMemory()
    await memory.add(MemoryContent(content="...", mime_type=MemoryMimeType.TEXT))
    ```

2. **`ChromaDBVectorMemory`**: Vector database-backed, uses semantic similarity for retrieval.

    ```python
    from autogen_ext.memory.chromadb import (
        ChromaDBVectorMemory,
        PersistentChromaDBVectorMemoryConfig,
        SentenceTransformerEmbeddingFunctionConfig,
    )
    memory = ChromaDBVectorMemory(config=PersistentChromaDBVectorMemoryConfig(
        collection_name="docs",
        persistence_path="./chroma_data",
        k=3,
        score_threshold=0.4,
        embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
            model_name="all-MiniLM-L6-v2"
        ),
    ))
    ```

3. **`RedisMemory`**: Persistent memory via Redis vector database.

    ```python
    from autogen_ext.memory.redis import RedisMemory, RedisMemoryConfig
    memory = RedisMemory(config=RedisMemoryConfig(
        redis_url="redis://localhost:6379",
        index_name="chat_history",
        prefix="memory",
    ))
    ```

4. **`Mem0Memory`**: Integration with the Mem0 cloud/local memory service.

### Memory Integration with Agents

When the agent processes a task, the memory lifecycle is:

1. Agent queries each memory store based on the current context
2. A `MemoryQueryEvent` is yielded with retrieved content
3. Retrieved memories are formatted as a system message: `"Relevant memory content (in chronological order):\n1. [content]\n2. [content]"`
4. The formatted memory is injected into the model context
5. The model generates a response with enhanced context

```python
agent = AssistantAgent(
    name="assistant",
    model_client=model_client,
    memory=[list_memory, chroma_memory],  # Multiple backends supported
)
```

### Agent State Serialization

All agents support explicit state management:

```python
state = await agent.save_state()    # Returns Mapping[str, Any]
await agent.load_state(state)       # Restores agent state
```

Teams also support state saving/loading and `reset()` to clear all agent states.

---

## 7. Runtime Architecture

### Core Layer: The Actor Model

At the Core layer, agents are actors that communicate through asynchronous messages. The runtime manages agent lifecycles, message routing, and execution.

### Agent Implementation (Core Layer)

Core-layer agents subclass `RoutedAgent` and use the `@message_handler` decorator:

```python
from autogen_core import RoutedAgent, message_handler, MessageContext

@dataclass
class TextMessage:
    content: str
    source: str

class MyAgent(RoutedAgent):
    @message_handler
    async def handle_text(self, message: TextMessage, ctx: MessageContext) -> None:
        # Process message
        await self.publish_message(
            TextMessage(content="response", source=self.id.key),
            topic_id=DefaultTopicId(),
        )
```

Conditional routing is supported via the `match` parameter:

```python
@message_handler(match=lambda msg, ctx: msg.source.startswith("user1"))
async def on_user1(self, message: TextMessage, ctx: MessageContext) -> None:
    ...
```

### Agent Registration

Agents are registered with the runtime using factory functions. The runtime creates instances lazily on first message delivery:

```python
from autogen_core import SingleThreadedAgentRuntime

runtime = SingleThreadedAgentRuntime()
await MyAgent.register(runtime, "my_agent_type", lambda: MyAgent())
```

**Key distinction**: "Agent type" (string identifier) differs from "agent class" (Python class). The same class can be registered under multiple types with different configurations.

### SingleThreadedAgentRuntime

The primary local development runtime. Processes all messages using a single `asyncio` queue.

```python
runtime = SingleThreadedAgentRuntime()
runtime.start()                    # Begin background message processing
# ... interact with agents ...
await runtime.stop_when_idle()     # Block until no unprocessed messages remain
await runtime.close()              # Release resources
```

Methods:
- `start()`: Begins background message processing
- `stop()`: Halts immediately (does not cancel in-progress handlers)
- `stop_when_idle()`: Blocks until message queue is empty and no active handlers
- `close()`: Releases resources

### DistributedRuntime (Experimental)

Supports agents across process and machine boundaries:
- **Host service**: Maintains connections to all worker runtimes, facilitates message delivery, keeps sessions for direct messages (RPCs)
- **Worker runtime**: Processes application code (agents), connects to host, advertises supported agent types

The same message-passing interface works transparently -- agents don't need to know whether they're local or distributed.

### Message Passing

Two communication modes:

**Direct messaging (send_message)** -- request/response pattern:

```python
response = await self.send_message(
    MyMessage("hello"),
    AgentId("target_agent_type", "instance_key"),
)
```

- Returns a response value
- Exceptions propagate back to sender
- Tight coupling (sender knows recipient)

**Broadcast (publish_message)** -- pub/sub pattern:

```python
await self.publish_message(
    MyMessage("broadcast"),
    topic_id=TopicId(type="news", source=self.id.key),
)
```

- Returns `None` (one-way)
- Exceptions are logged but not propagated
- Agents don't receive their own published messages
- Loose coupling (topic-based)

### Topics and Subscriptions

A **TopicId** has two components:
- `type`: Application-defined identifier (e.g., `"github_issues"`)
- `source`: Unique identifier within the type (e.g., `"repo/issues/42"`)

**TypeSubscription** maps topic types to agent types:

```python
from autogen_core import TypeSubscription

# All messages to "default" topic go to "triage_agent" type
sub = TypeSubscription(topic_type="default", agent_type="triage_agent")
await runtime.add_subscription(sub)
```

When a message arrives on a topic, the runtime constructs `AgentId(agent_type, topic_source)` and routes accordingly. This enables multi-tenant isolation -- each topic source gets its own agent instance.

Convenience decorators:
- `@default_subscription` -- subscribes to `DefaultTopicId`
- `@type_subscription(topic_type="X")` -- subscribes to a specific topic type

### AgentChat Integration with Core

AgentChat's `AssistantAgent` can be wrapped inside a Core `RoutedAgent` to participate in the Core runtime's message-passing infrastructure while retaining its high-level functionality.

---

## 8. Termination Conditions

Termination conditions are callable objects that evaluate message sequences and return a `StopMessage` to halt team execution, or `None` to continue. They are **stateful** but automatically reset after each `run()` / `run_stream()` call.

### Built-in Conditions

| Class | Triggers when... |
|-------|-----------------|
| `MaxMessageTermination(max_messages=N)` | N total messages (agent + task) have been produced |
| `TextMentionTermination("WORD")` | Specified text appears in any message |
| `TextMessageTermination()` | An agent produces a `TextMessage` (not tool-related) |
| `StopMessageTermination()` | An agent produces a `StopMessage` |
| `TokenUsageTermination(max_tokens=N)` | Prompt or completion token usage exceeds threshold |
| `TimeoutTermination(timeout_seconds=N)` | Wall-clock time exceeds N seconds |
| `HandoffTermination(target="agent_name")` | A handoff to the specified target is requested |
| `SourceMatchTermination(sources=["agent"])` | A specified agent has responded |
| `ExternalTermination()` | External code calls `.set()` on the condition |
| `FunctionCallTermination(function_name="X")` | A `ToolCallExecutionEvent` with matching function executes |
| `FunctionalTermination(func)` | A custom function returns `True` on the latest messages |

### Combining Conditions

Conditions can be combined with `|` (OR) and `&` (AND):

```python
# Stop when EITHER 10 messages reached OR "APPROVE" is mentioned
termination = MaxMessageTermination(10) | TextMentionTermination("APPROVE")

# Stop when BOTH a specific agent has spoken AND "DONE" is mentioned
termination = SourceMatchTermination(["reviewer"]) & TextMentionTermination("DONE")
```

### Custom Conditions

Subclass `TerminationCondition`:

```python
from autogen_agentchat.conditions import TerminationCondition

class MyTermination(TerminationCondition):
    async def __call__(self, messages: Sequence[...]) -> StopMessage | None:
        for msg in messages:
            if some_custom_logic(msg):
                return StopMessage(content="Custom stop", source="termination")
        return None

    async def reset(self) -> None:
        # Reset internal state between runs
        pass
```

### Integration with Teams

Termination conditions are evaluated after each agent response in group chats. The condition receives the "delta sequence" -- the messages produced since the last evaluation. The `TaskResult.stop_reason` attribute explains why execution stopped.

---

## 9. Comparison Notes: AutoGen 0.4 vs. a Minimal Custom Agent Loop

### Strengths of AutoGen 0.4

1. **Multi-agent orchestration out of the box**: RoundRobinGroupChat, SelectorGroupChat, Swarm, and GraphFlow provide sophisticated coordination patterns that would require significant custom code to replicate.

2. **Distributed runtime**: The actor model and DistributedRuntime enable scaling agents across processes and machines, something a minimal loop has no path to.

3. **Rich tool ecosystem**: FunctionTool, MCP integration, LangChain adapters, and built-in tools (HttpTool, PythonCodeExecutionTool) provide broad capability without custom plumbing.

4. **Memory abstraction**: The `Memory` protocol with ListMemory, ChromaDB, Redis, and Mem0 backends provides production-ready persistent memory out of the box.

5. **Observability**: OpenTelemetry integration, structured event yielding (ToolCallRequestEvent, ToolCallExecutionEvent, MemoryQueryEvent) make debugging and monitoring straightforward.

6. **State management**: Explicit `save_state()`/`load_state()` on agents and teams enables checkpointing and resumption.

7. **Type safety**: Full typing throughout the library catches errors at development time.

8. **Termination flexibility**: Composable termination conditions (AND/OR) cover most stopping scenarios without custom code.

### Weaknesses of AutoGen 0.4

1. **Complexity overhead**: The three-layer architecture (Core + AgentChat + Extensions), actor model, topics, subscriptions, and multiple team types create significant conceptual overhead. A minimal loop can be understood in minutes; AutoGen requires studying multiple abstraction layers.

2. **Opinionated abstractions**: The `BaseChatAgent` -> `on_messages` -> `Response` pattern imposes a specific message-flow model. A minimal custom loop can adapt its message handling to exactly what's needed.

3. **Heavyweight dependencies**: The full installation pulls `autogen-core`, `autogen-agentchat`, `autogen-ext`, plus provider-specific packages (OpenAI, Docker, ChromaDB, etc.). A minimal loop might need only `anthropic` or `openai`.

4. **Async-first complexity**: Everything is `async`/`await` with `CancellationToken`, `AsyncGenerator`, and `asyncio.gather`. Simpler synchronous patterns are not first-class.

5. **Black-box tool execution**: Tools execute within the agent's `on_messages_stream` loop; intercepting or customizing the tool-call flow requires understanding the internal lifecycle deeply. A minimal loop gives direct control over every tool call.

6. **No built-in context compaction**: While `BufferedChatCompletionContext` and `TokenLimitedChatCompletionContext` provide basic truncation, there is no summarization-based compaction. A custom loop can implement smarter compaction strategies (head+tail retention, summarization, etc.).

7. **Framework lock-in**: Agents must conform to `BaseChatAgent` or `RoutedAgent` interfaces. Integrating non-AutoGen agents requires wrapping them in AutoGen's abstractions (e.g., `SocietyOfMindAgent`).

8. **Evolving API**: As a 0.4.x release, the API is still changing. Several components (GraphFlow, DistributedRuntime, CodeExecutorAgent) are marked as experimental.

### When to Choose Each

| Choose AutoGen 0.4 when... | Choose a minimal custom loop when... |
|-----------------------------|--------------------------------------|
| You need multi-agent coordination | You have a single-agent use case |
| You need distributed agent execution | Simplicity and transparency matter most |
| You want pre-built team patterns | You need full control over every LLM call |
| You need MCP/tool ecosystem integration | You want minimal dependencies |
| You're building a production system with monitoring | You're building a focused, lightweight tool |
| You need persistent memory with vector search | Simple sliding-window context suffices |

---

## Sources

- [microsoft/autogen GitHub Repository](https://github.com/microsoft/autogen)
- [AutoGen Documentation (stable)](https://microsoft.github.io/autogen/stable//index.html)
- [AgentChat User Guide](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/index.html)
- [Agents Tutorial](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/agents.html)
- [Teams Tutorial](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/teams.html)
- [Termination Conditions](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/termination.html)
- [Selector Group Chat](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/selector-group-chat.html)
- [Swarm Pattern](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/swarm.html)
- [GraphFlow (Workflows)](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/graph-flow.html)
- [Memory and RAG](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/memory.html)
- [Tools (Core)](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/components/tools.html)
- [Model Context](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/components/model-context.html)
- [Model Clients](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/components/model-clients.html)
- [Agent and Agent Runtime](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/agent-and-agent-runtime.html)
- [Topic and Subscription](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/core-concepts/topic-and-subscription.html)
- [Message and Communication](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/framework/message-and-communication.html)
- [Workbench and MCP](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/components/workbench.html)
- [autogen_agentchat.agents API Reference](https://microsoft.github.io/autogen/stable//reference/python/autogen_agentchat.agents.html)
- [autogen_agentchat.conditions API Reference](https://microsoft.github.io/autogen/stable/reference/python/autogen_agentchat.conditions.html)
- [autogen_agentchat.teams API Reference](https://microsoft.github.io/autogen/stable//reference/python/autogen_agentchat.teams.html)
- [AutoGen Reimagined: Launching AutoGen 0.4 (Blog)](https://devblogs.microsoft.com/autogen/autogen-reimagined-launching-autogen-0-4/)
- [AutoGen v0.4: Reimagining the Foundation (Microsoft Research)](https://www.microsoft.com/en-us/research/blog/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/)
- [Migration Guide v0.2 to v0.4](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/migration-guide.html)
- [AssistantAgent Source Code](https://microsoft.github.io/autogen/stable//_modules/autogen_agentchat/agents/_assistant_agent.html)
