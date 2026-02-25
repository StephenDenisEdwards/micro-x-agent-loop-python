# Haystack 2.x Architecture Research

> **Date:** 2026-02-24
> **Subject:** deepset Haystack — pipeline-based AI orchestration framework
> **Version analyzed:** Haystack 2.24.x (latest stable as of research date)
> **Sources:** Official docs (docs.haystack.deepset.ai), GitHub (deepset-ai/haystack), release blog posts

---

## 1. Overview

### What Is Haystack?

Haystack is an **open-source AI orchestration framework** for building production-ready LLM applications in Python. It is developed and maintained by **deepset** (deepset-ai on GitHub). The framework structures applications as explicit, modular **pipelines** composed of retrievers, routers, memory layers, tools, evaluators, and generators.

- **Repository:** <https://github.com/deepset-ai/haystack>
- **License:** Apache-2.0
- **Language:** Python (pip package: `haystack-ai`)
- **Stars:** ~24.3k (as of Feb 2026)
- **Current version:** 2.24.1 (released 2026-02-12)
- **Install:** `pip install haystack-ai`

### Core Philosophy

Haystack 2.x is built on three foundational design principles:

1. **Technology agnosticism** — Users select vendors/technologies per component (OpenAI, Anthropic, Hugging Face, Ollama, etc.) and can swap them without rewriting the pipeline.
2. **Explicitness** — Data flows only through established connections. Components do not have implicit access to a global context. This aids speed, transparency, and debugging.
3. **Extensibility** — A uniform component interface (`@component` decorator) enables first-party, community, and custom components to compose seamlessly.

### The Haystack 2.x Rewrite

Haystack was originally created in 2020 for semantic search, retrieval, and extractive question-answering. The 2023 LLM boom revealed that the 1.x architecture made assumptions poorly suited to generative AI:

| Aspect | Haystack 1.x | Haystack 2.x |
|---|---|---|
| Pipeline graph | Acyclic directed graphs only (no loops) | Directed multigraphs with cycles, branching, looping |
| Component model | Nodes, pipeline components — inconsistent naming | Unified `@component` protocol with `run()` method |
| Data flow | Implicit, broad data access | Explicit connections, typed sockets |
| Custom components | Difficult to create | Simple protocol: `@component` + `run()` + output types |
| Serialization | Limited | Full YAML serialization with `to_dict`/`from_dict` |
| Agents | Not natively supported | First-class `Agent` component with tool loop |
| Document stores | Fragmented abstractions | Unified `DocumentStore` protocol |

The 2.0 release (2024) was a **ground-up rewrite** that preserved the pipeline-centric philosophy while modernizing every subsystem.

---

## 2. Pipeline Architecture

### The Pipeline Class

The `Pipeline` class (`haystack.core.pipeline.pipeline.Pipeline`) is the central orchestration unit. A pipeline is a **directed multigraph** of components. Building a pipeline is a two-step process:

```python
from haystack import Pipeline

pipe = Pipeline()

# Step 1: Add components (no ordering implied)
pipe.add_component("retriever", InMemoryBM25Retriever(document_store=doc_store))
pipe.add_component("prompt_builder", ChatPromptBuilder(template=template))
pipe.add_component("llm", OpenAIChatGenerator(model="gpt-4o-mini"))

# Step 2: Connect components (defines the graph edges)
pipe.connect("retriever.documents", "prompt_builder.documents")
pipe.connect("prompt_builder.prompt", "llm.messages")

# Execute
result = pipe.run({
    "retriever": {"query": "What is Haystack?"},
    "prompt_builder": {"query": "What is Haystack?"}
})
```

### Data Flow and Typed Sockets

Each component exposes **input sockets** (defined by `run()` method parameters) and **output sockets** (defined by `@component.output_types()`). When you call `pipe.connect("producer.output_name", "consumer.input_name")`, the pipeline validates that the output type matches the input type **at connection time**, not at execution time.

Individual values flow only through established connections. Not all components see all data — this is a deliberate design choice for speed, transparency, and security.

### The DAG Model (Extended)

Despite being called a "DAG" historically, Haystack 2.x pipelines are **not** strictly acyclic — they are directed multigraphs that support:

- **Branching:** Multiple parallel branches processing data simultaneously
- **Cycles/Loops:** Output of a later component fed back to an earlier one
- **Standalone components:** Components with no connections to others
- **Multiple connections:** A single output can feed multiple inputs

The pipeline maintains an internal **visit counter** per component. Each time a component runs, its count increments. The pipeline returns only the last-produced output for each component, though intermediate outputs can be captured via `include_outputs_from` in `Pipeline.run()`.

### Pipeline Execution

When `Pipeline.run()` is called:

1. Initial inputs are delivered to the specified components.
2. The pipeline builds a work queue of components whose required inputs are satisfied.
3. Components execute in dependency order. When a component runs, its outputs are routed to connected downstream components.
4. The process continues until the work queue is empty (no more components can execute) or a safety limit is hit.

### AsyncPipeline

`AsyncPipeline` enables concurrent component execution when dependencies allow:

```python
from haystack import AsyncPipeline

pipe = AsyncPipeline()
# ... add_component / connect as usual ...
result = await pipe.run_async({"retriever": {"query": "..."}})
```

Key features:
- Parallel execution of independent branches (e.g., multiple retrievers)
- `concurrency_limit` parameter controls maximum simultaneous component executions
- `run_async_generator()` returns an `AsyncIterator` for progressive results
- All core chat generators and retrievers support `run_async` natively

---

## 3. Agent Loop

### The Agent Component

The `Agent` class (`haystack.components.agents.Agent`) is a **loop-based component** that iteratively calls a chat-based LLM and external tools until an exit condition is met. Despite Haystack being pipeline-centric, the Agent itself is an **internal loop** — but it participates in the broader pipeline as a single component.

```python
from haystack.components.agents import Agent
from haystack.components.generators.chat import OpenAIChatGenerator

agent = Agent(
    chat_generator=OpenAIChatGenerator(model="gpt-4o-mini"),
    tools=[search_tool, calculator_tool],
    system_prompt="You are a research assistant.",
    exit_conditions=["text"],
    max_agent_steps=20,
    streaming_callback=print_streaming_chunk,
)

result = agent.run(messages=[ChatMessage.from_user("What is 7 * 6?")])
print(result["messages"][-1].text)
```

### Constructor Signature

```python
Agent(
    *,
    chat_generator: ChatGenerator,                    # Required: LLM that supports tools
    tools: ToolsType | None = None,                   # List of Tool/Toolset objects
    system_prompt: str | None = None,                 # System message template
    user_prompt: str | None = None,                   # User message template
    required_variables: list[str] | Literal["*"] | None = None,
    exit_conditions: list[str] | None = None,         # Default: ["text"]
    state_schema: dict[str, Any] | None = None,       # Extra state for tools
    max_agent_steps: int = 100,                       # Safety limit
    streaming_callback: StreamingCallbackT | None = None,
    raise_on_tool_invocation_failure: bool = False,
    tool_invoker_kwargs: dict[str, Any] | None = None,
    confirmation_strategies: dict[str | tuple[str, ...], ConfirmationStrategy] | None = None,
)
```

### How the Agent Loop Works

The `run()` method implements the core loop:

1. **Initialize** execution context with state, messages, and component tracking.
2. **Loop** up to `max_agent_steps`:
   a. Call the `chat_generator` with current messages and available tools.
   b. Check if the LLM response contains tool calls.
   c. If tool calls exist: invoke them via an internal `ToolInvoker`, append tool result messages, check confirmation strategies, and loop back.
   d. If no tool calls (text-only response): check exit conditions.
3. **Return** the full conversation history and any state values.

### Exit Conditions

Exit conditions are a list of strings:
- `"text"` — Exit when the LLM returns only a text response (no tool calls). This is the default.
- Tool names — Exit after a specific tool is invoked (e.g., `"final_answer"`).

The `_check_exit_conditions` method examines all LLM messages, checking if any tool calls match exit conditions. It also verifies that the matched tool did not produce an error — if it did, the loop continues.

### State Management

The `state_schema` parameter defines extra runtime state that tools can read from and write to during execution:

```python
agent = Agent(
    chat_generator=generator,
    tools=[my_tool],
    state_schema={
        "documents": {"type": list[Document], "handler": merge_lists},
        "context": {"type": str},
    },
)
```

The state always includes a `messages` key (of type `list[ChatMessage]` with a `merge_lists` handler). Tools can declare `inputs_from_state` and `outputs_to_state` to interact with the state.

### Agent vs. Pipeline-Based Tool Loop

Before the dedicated `Agent` component existed, Haystack users built agentic behavior by composing pipeline loops manually with `ConditionalRouter`, `ChatGenerator`, and `ToolInvoker`:

```python
# Manual agentic pipeline (pre-Agent component approach)
pipe = Pipeline(max_runs_per_component=10)
pipe.add_component("generator", OpenAIChatGenerator(tools=[tool]))
pipe.add_component("router", ConditionalRouter(routes=[
    {"condition": "{{ replies[0].tool_calls | length > 0 }}",
     "output": "{{ replies }}", "output_name": "has_tools",
     "output_type": list[ChatMessage]},
    {"condition": "{{ replies[0].tool_calls | length == 0 }}",
     "output": "{{ replies }}", "output_name": "final",
     "output_type": list[ChatMessage]},
]))
pipe.add_component("tool_invoker", ToolInvoker(tools=[tool]))
pipe.connect("generator.replies", "router.replies")
pipe.connect("router.has_tools", "tool_invoker")
pipe.connect("tool_invoker.tool_messages", "generator.messages")  # loop back
```

The dedicated `Agent` component encapsulates this pattern into a single reusable component. Internally, it still uses a `ToolInvoker` and the provided `ChatGenerator`, but manages the loop, state, and exit conditions automatically.

---

## 4. Component System

### The @component Decorator

Any Python class can become a Haystack component by applying `@component` and implementing a `run()` method:

```python
from haystack import component
from typing import List

@component
class WelcomeTextGenerator:
    """Generates a welcome message."""

    @component.output_types(welcome_text=str, note=str)
    def run(self, name: str):
        return {
            "welcome_text": f"Hello {name}, welcome to Haystack!",
            "note": "welcome message is ready",
        }
```

### Component Protocol Requirements

1. **`@component` class decorator** — Marks the class as a pipeline-compatible component.
2. **`run()` method** — Required. Parameters define input sockets; return dict defines outputs.
3. **`@component.output_types(...)` decorator on `run()`** — Declares output names and types. The returned dict keys must match.
4. **Type annotations** — All inputs and outputs must be type-annotated. The pipeline validates type compatibility at connection time.

### Input/Output Configuration

**Static inputs** — Declared as `run()` parameters with type annotations:
```python
def run(self, query: str, documents: List[Document], top_k: Optional[int] = None):
```
- Required parameters = mandatory inputs
- Parameters with defaults = optional inputs

**Dynamic inputs** — Set at runtime:
```python
component.set_input_type(self, name="extra", type=str, default=None)
component.set_output_types(self, result=str)
```

**Output types** — Declared via decorator or `set_output_types()`.

### Component Lifecycle

- **`__init__()`** — Configuration and lightweight setup. Init parameters must be stored as instance attributes (required for serialization).
- **`warm_up()`** — Optional. Loads heavy resources (models, embeddings). Called automatically on first pipeline run, or manually via `component.warm_up()`.
- **`run()`** — Core execution. Called each time the component is invoked in the pipeline.

### Immutability Rule

Components must **not mutate their inputs** directly. Instead, work on copies:
```python
import copy
docs = copy.deepcopy(documents)
```

### SuperComponents

A `SuperComponent` wraps an entire pipeline as a single component, enabling composition and reuse:

```python
from haystack.core.super_component import super_component, SuperComponent

@super_component
class HybridRetriever:
    def __init__(self, document_store, embedder_model="BAAI/bge-small-en-v1.5"):
        self.pipeline = Pipeline()
        self.pipeline.add_component("text_embedder",
            SentenceTransformersTextEmbedder(embedder_model))
        self.pipeline.add_component("embedding_retriever",
            InMemoryEmbeddingRetriever(document_store))
        self.pipeline.add_component("bm25_retriever",
            InMemoryBM25Retriever(document_store))
        self.pipeline.add_component("joiner", DocumentJoiner())
        self.pipeline.connect("text_embedder.embedding",
            "embedding_retriever.query_embedding")
        self.pipeline.connect("embedding_retriever", "joiner")
        self.pipeline.connect("bm25_retriever", "joiner")
```

Features:
- `input_mapping` / `output_mapping` control which internal sockets are exposed
- Auto-detection of mappings when unambiguous
- Automatic serialization via the decorator
- Can be visualized as a black-box or expanded (`super_component_expansion=True`)
- Built-in examples: `DocumentPreprocessor`, `MultiFileConverter`, `OpenSearchHybridRetriever`

---

## 5. Tool System

### Three Ways to Create Tools

#### 1. `Tool` Class (Explicit)

```python
from haystack.tools import Tool

def add(a: int, b: int) -> int:
    return a + b

add_tool = Tool(
    name="addition_tool",
    description="Adds two numbers together",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"}
        },
        "required": ["a", "b"],
    },
    function=add,
)
```

The `Tool` dataclass attributes:
- `name: str` — Identifier used by the LLM
- `description: str` — LLM-visible explanation (critical for correct invocation)
- `parameters: dict` — JSON Schema defining expected inputs
- `function: Callable` — The callable that executes the tool logic
- `outputs_to_string: dict | None` — Controls how outputs are converted to strings for LLM consumption
- `inputs_from_state: dict | None` — Maps state keys to tool input parameters
- `outputs_to_state: dict | None` — Maps tool outputs back to agent state

#### 2. `@tool` Decorator (Auto-Inferred)

```python
from typing import Annotated, Literal
from haystack.tools import tool

@tool
def get_weather(
    city: Annotated[str, "the city for which to get the weather"] = "Munich",
    unit: Annotated[Literal["Celsius", "Fahrenheit"], "the unit"] = "Celsius",
):
    """A simple function to get the current weather for a location."""
    return f"Weather report for {city}: 20 {unit}, sunny"
```

The decorator automatically:
- Uses the function name as the tool name
- Uses the docstring as the description
- Generates JSON Schema from type annotations and `Annotated` metadata

#### 3. `ComponentTool` (Wrapping Components/Pipelines)

```python
from haystack.tools.component_tool import ComponentTool

web_tool = ComponentTool(
    component=SerperDevWebSearch(),
    name="web_search",
    description="Search the web for information",
)

# Wrapping a pipeline via SuperComponent
search_component = SuperComponent(
    pipeline=search_pipeline,
    input_mapping={"query": ["search.query"]},
    output_mapping={"output_adapter.output": "search_result"},
)
search_tool = ComponentTool(
    name="search",
    component=search_component,
    outputs_to_string={"source": "search_result"},
)
```

### Toolset

`Toolset` groups multiple tools into a manageable unit:

```python
from haystack.tools import Toolset

math_tools = Toolset([add_tool, subtract_tool, multiply_tool])

# Pass to Agent or ChatGenerator
agent = Agent(chat_generator=gen, tools=[math_tools, weather_tool])
```

Toolset implements the collection interface (`__iter__`, `__contains__`, `__len__`, `__getitem__`).

### Tool Invocation Flow

The `ToolInvoker` component (`haystack.components.tools.ToolInvoker`) executes tool calls:

```python
from haystack.components.tools import ToolInvoker

tool_invoker = ToolInvoker(
    tools=[weather_tool],
    raise_on_failure=False,           # Return error as ChatMessage instead of raising
    convert_result_to_json_string=True # Use json.dumps instead of str()
)

# Process LLM replies that contain tool calls
result = tool_invoker.run(messages=llm_replies)
tool_messages = result["tool_messages"]  # List[ChatMessage] with ToolCallResult
```

### ChatMessage Tool Call Integration

The `ChatMessage` dataclass supports flexible content types:

```python
from haystack.dataclasses import ChatMessage, ToolCall

# LLM produces a tool call
tool_call = ToolCall(tool_name="weather_tool", arguments={"location": "Rome"})
assistant_msg = ChatMessage.from_assistant(tool_calls=[tool_call])

# Tool produces a result
tool_msg = ChatMessage.from_tool(
    tool_result="temperature: 25C",
    origin=tool_call,
    error=False,
)
```

The `ChatMessage.content` is a list supporting `TextContent`, `ToolCall`, and `ToolCallResult` types.

---

## 6. Chat and Model Integration

### Generator vs. ChatGenerator

Haystack distinguishes two component families:

| Aspect | Generator | ChatGenerator |
|---|---|---|
| Input | Plain string prompt | `List[ChatMessage]` |
| Output | `replies: List[str]` | `replies: List[ChatMessage]` |
| Use case | Single-turn text generation | Multi-turn chat, tool calling |
| Example | `OpenAIGenerator` | `OpenAIChatGenerator` |

### Supported Model Providers (40+ components)

**Proprietary:**
- OpenAI (`OpenAIChatGenerator`) — GPT-3.5-turbo, GPT-4, GPT-4o, etc.
- Azure OpenAI (`AzureOpenAIChatGenerator`)
- Anthropic (`AnthropicChatGenerator`) — Claude 3, 3.5, 4 series
- Google (`GoogleAIGeminiChatGenerator`)
- Cohere (`CohereChatGenerator`)
- Mistral (`MistralChatGenerator`)
- Amazon Bedrock (`AmazonBedrockChatGenerator`)
- Nvidia (`NvidiaChatGenerator`)

**Open/Self-hosted:**
- Hugging Face (`HuggingFaceAPIChatGenerator`, `HuggingFaceLocalChatGenerator`)
- Ollama (`OllamaChatGenerator`)
- Llama.cpp (`LlamaCppChatGenerator`)
- Together AI, Vertex AI, Watsonx, etc.

**Specialized:** Image generation (DALL-E), image captioning, code generation, fallback generators.

### AnthropicChatGenerator Example

```python
from haystack_integrations.components.generators.anthropic import AnthropicChatGenerator

generator = AnthropicChatGenerator(
    model="claude-3-5-sonnet-20240620",
    # api_key defaults to ANTHROPIC_API_KEY env var
    generation_kwargs={"max_tokens": 1024},
    streaming_callback=print_streaming_chunk,
    tools=[math_toolset, weather_tool],
)

result = generator.run(messages=[ChatMessage.from_user("Hello!")])
# Returns: {"replies": [ChatMessage], "meta": [dict with token counts]}
```

Features:
- Prompt caching via `extra_headers` and `cache_control` metadata
- Multimodal support via `ImageContent.from_file_path()`
- Tool calling support with `Tool`, `Toolset`, and `ComponentTool`

### Streaming

All ChatGenerators support streaming via a callback:

```python
from haystack.components.generators.utils import print_streaming_chunk

generator = OpenAIChatGenerator(
    model="gpt-4o-mini",
    streaming_callback=print_streaming_chunk,  # Built-in utility
)
```

Streaming delivers text tokens and tool call events in real-time. Limitation: streaming works only with a single response (not multiple choices).

---

## 7. Data Stores and Retrievers

### DocumentStore Protocol

All document stores implement a common protocol with four mandatory methods:

```python
class DocumentStore(Protocol):
    def count_documents(self) -> int: ...
    def filter_documents(self, filters: dict) -> List[Document]: ...
    def write_documents(self, documents: List[Document],
                       policy: DuplicatePolicy) -> int: ...
    def delete_documents(self, document_ids: List[str]) -> None: ...
```

### The Document Dataclass

```python
from haystack import Document

doc = Document(
    content="This is the document text",
    meta={"source": "wikipedia", "title": "Haystack"},
    id="custom-id",          # Auto-generated from content hash if omitted
    embedding=[0.1, 0.2, ...],  # Optional vector embedding
)
```

### DuplicatePolicy

```python
from haystack.document_stores.types import DuplicatePolicy

# Options:
DuplicatePolicy.OVERWRITE  # Replace existing documents with same ID
DuplicatePolicy.SKIP       # Ignore duplicates silently
DuplicatePolicy.FAIL       # Raise error on duplicates
DuplicatePolicy.NONE       # Use store's default behavior
```

### Available Document Stores

**Built-in:**
- `InMemoryDocumentStore` — In-memory, ephemeral, great for experiments (not production)

**Integration packages:**
- Elasticsearch (`ElasticsearchDocumentStore`)
- OpenSearch (`OpenSearchDocumentStore`)
- Chroma (`ChromaDocumentStore`)
- Weaviate (`WeaviateDocumentStore`)
- Pinecone (`PineconeDocumentStore`)
- Qdrant (`QdrantDocumentStore`)
- MongoDB Atlas (`MongoDBAtlasDocumentStore`)
- Neo4j, pgvector, Milvus, and many others

### Retriever Types

Retrievers are specialized per document store. Naming convention: `[DocumentStore][RetrievalMethod]Retriever`.

1. **Sparse / BM25 Retrievers** — Keyword-based weighted word overlap (e.g., `InMemoryBM25Retriever`, `ElasticsearchBM25Retriever`)
2. **Dense / Embedding Retrievers** — Semantic similarity via vector embeddings (e.g., `InMemoryEmbeddingRetriever`, `QdrantEmbeddingRetriever`)
3. **Sparse Embedding Retrievers** — SPLADE-like approaches combining keyword and semantic matching
4. **FilterRetriever** — Retrieves documents by metadata filters only

### Embedders (Separate Components)

In Haystack 2.x, embedding creation is a **separate component** (not part of the retriever):

- `SentenceTransformersTextEmbedder` — For query embedding
- `SentenceTransformersDocumentEmbedder` — For document embedding at indexing time
- `OpenAITextEmbedder`, `OpenAIDocumentEmbedder`, etc.

### RAG Pipeline Example

```python
from haystack import Pipeline
from haystack.components.builders import ChatPromptBuilder
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.document_stores.in_memory import InMemoryDocumentStore

doc_store = InMemoryDocumentStore()
# ... write documents with embeddings ...

template = [ChatMessage.from_user("""
Given these documents: {{ documents }}
Answer: {{ query }}
""")]

pipe = Pipeline()
pipe.add_component("embedder", SentenceTransformersTextEmbedder())
pipe.add_component("retriever", InMemoryEmbeddingRetriever(document_store=doc_store))
pipe.add_component("prompt", ChatPromptBuilder(template=template))
pipe.add_component("llm", OpenAIChatGenerator(model="gpt-4o-mini"))

pipe.connect("embedder.embedding", "retriever.query_embedding")
pipe.connect("retriever.documents", "prompt.documents")
pipe.connect("prompt.prompt", "llm.messages")

result = pipe.run({
    "embedder": {"text": "What is Haystack?"},
    "prompt": {"query": "What is Haystack?"},
})
```

### Hybrid Retrieval

Combining sparse and dense retrievers in one pipeline:

```python
pipe.add_component("bm25", InMemoryBM25Retriever(doc_store))
pipe.add_component("embedding", InMemoryEmbeddingRetriever(doc_store))
pipe.add_component("joiner", DocumentJoiner())
pipe.connect("bm25", "joiner")
pipe.connect("embedding", "joiner")
```

### Indexing Pipeline

Separate pipelines for writing documents:

```python
from haystack.components.writers import DocumentWriter
from haystack.components.preprocessors import DocumentCleaner, DocumentSplitter

indexing = Pipeline()
indexing.add_component("cleaner", DocumentCleaner())
indexing.add_component("splitter", DocumentSplitter(split_by="sentence", split_length=3))
indexing.add_component("embedder", SentenceTransformersDocumentEmbedder())
indexing.add_component("writer", DocumentWriter(document_store=doc_store))
indexing.connect("cleaner", "splitter")
indexing.connect("splitter", "embedder")
indexing.connect("embedder", "writer")
```

---

## 8. Pipeline Features

### Branching

Pipelines support concurrent parallel branches that process data simultaneously. Example: multiple file converters handling different file types in one pipeline, then merging results via a `DocumentJoiner`.

### Looping

Components can form feedback loops. The `ConditionalRouter` component enables conditional branching based on Jinja2 expressions:

```python
from haystack.components.routers import ConditionalRouter

routes = [
    {
        "condition": "{{ 'correct' in replies[0].text }}",
        "output": "{{ replies }}",
        "output_name": "final_answer",
        "output_type": list[ChatMessage],
    },
    {
        "condition": "{{ 'correct' not in replies[0].text }}",
        "output": "{{ replies }}",
        "output_name": "retry",
        "output_type": list[ChatMessage],
    },
]
router = ConditionalRouter(routes, unsafe=True)
```

**Loop termination:**
1. **Natural completion** — The work queue empties (router stops feeding inputs back).
2. **Safety limit** — `max_runs_per_component` (default: 100) enforces a per-component execution cap. Exceeding it raises `PipelineMaxComponentRuns`.

```python
pipe = Pipeline(max_runs_per_component=5)
```

**Variadic socket behavior in loops:**
- **Greedy sockets** — Consume one value per execution, preventing infinite retriggering.
- **Lazy sockets** — Accumulate values across iterations for collecting partial results.

**BranchJoiner** merges inputs from multiple sources (initial inputs + loop feedback):

```python
from haystack.components.joiners import BranchJoiner
pipe.add_component("joiner", BranchJoiner(type_=list[ChatMessage]))
```

### Serialization

Pipelines serialize to YAML (the only format currently supported natively):

```python
# Serialize
yaml_str = pipe.dumps()
pipe.dump(open("pipeline.yaml", "w"))

# Deserialize
pipe = Pipeline.loads(yaml_str)
pipe = Pipeline.load(open("pipeline.yaml"))

# Dict intermediate format
pipe_dict = pipe.to_dict()
pipe = Pipeline.from_dict(pipe_dict)
```

**Component serialization requirements:**
- Components must implement `to_dict()` and `from_dict()` (provided automatically for simple components via `default_to_dict`/`default_from_dict`).
- Init parameters must be stored as instance attributes with a 1:1 mapping.
- Secrets are stored securely, not in plain text.
- Non-JSON-serializable types (like sets) require custom `to_dict`/`from_dict` methods.

**Custom marshalling:** Implement the `Marshaller` protocol (`marshal()`/`unmarshal()`) for non-YAML formats (TOML, JSON, etc.).

**Deserialization callbacks:** Modify components during loading:
```python
Pipeline.loads(yaml_str, callbacks=DeserializationCallbacks(
    component_pre_init=my_callback
))
```

### Pipeline Validation

Validation occurs during `connect()`:
- Checks that both components exist in the pipeline.
- Verifies output type matches input type.
- Checks input occupancy (prevents conflicts for non-Variadic inputs).
- Generates detailed error messages for quick resolution.

### Pipeline Visualization

```python
pipe.draw("pipeline.png")   # Save as image
pipe.show()                  # Display in notebook
```

### Debugging

- `include_outputs_from` parameter in `run()` captures intermediate outputs
- Tracing support with OpenTelemetry and Datadog
- Structured logging with correlation tracing
- Breakpoints for state inspection at specific iterations

### Deployment: Hayhooks

Hayhooks is a dedicated deployment system that serves Haystack pipelines via HTTP endpoints with automatically generated REST schemas.

---

## 9. Comparison Notes: Pipeline-Based vs. Loop-Based Agent Architecture

### Haystack's Hybrid Approach

Haystack takes a **pipeline-first** approach but acknowledges that agents inherently need loops. The `Agent` component is a loop internally but presents itself as a single pipeline component externally. This is a pragmatic hybrid: the pipeline handles data flow orchestration while the agent handles iterative reasoning.

### Strengths of Haystack's Pipeline Approach

1. **Composability and reuse** — Components and SuperComponents can be mixed and matched. A RAG pipeline built once can be wrapped as a `ComponentTool` and handed to an agent. Pipelines are building blocks, not monoliths.

2. **Type safety and validation** — The typed socket system catches connection errors at build time, not runtime. This is a significant advantage over untyped loop architectures where data format mismatches surface only during execution.

3. **Explicit data flow** — Every piece of data flows through declared connections. This makes pipelines auditable, debuggable, and easier to reason about compared to opaque agent loops where state is implicitly passed.

4. **Serialization and portability** — Pipelines serialize to YAML, enabling storage, versioning, and sharing. A pipeline definition is a declarative artifact, not just imperative code.

5. **Vendor agnosticism** — Swapping OpenAI for Anthropic means changing one component. The rest of the pipeline is unaffected.

6. **Built-in observability** — OpenTelemetry, Datadog, structured logging, and tracing are first-class concerns.

7. **Rich ecosystem** — 40+ generator components, 15+ document store integrations, embedders, retrievers, preprocessors, routers — all composable.

8. **Production deployment** — Hayhooks provides HTTP serving out of the box. Async pipelines enable concurrent execution.

### Weaknesses / Trade-offs

1. **Complexity for simple cases** — A minimal "call LLM, check for tool calls, invoke, loop" pattern requires significantly more code and concepts in Haystack (Pipeline, Components, connections, routers, sockets) than a simple while loop.

2. **Abstraction overhead** — The component protocol, typed sockets, and pipeline graph add indirection. Debugging a pipeline graph requires understanding the execution model, visit counters, and work queue semantics.

3. **Learning curve** — The distinction between Generator/ChatGenerator, Embedder/Retriever separation, SuperComponents, input/output mappings, ConditionalRouter Jinja2 conditions — there are many concepts to internalize.

4. **Agent loop is still a loop** — The `Agent` component internally runs a while loop, similar to any custom agent loop. The pipeline abstraction does not eliminate the loop; it encapsulates it. The pipeline graph enables composition around the agent, but the core agent reasoning is loop-based.

5. **Serialization limitations** — Only YAML is natively supported. Custom marshallers are needed for other formats.

6. **Integration package fragmentation** — Anthropic, Ollama, and many other providers require separate pip packages (`haystack-integrations`), adding dependency management overhead.

### Key Architectural Contrast with a Minimal Custom Agent Loop

| Aspect | Minimal Custom Loop | Haystack Pipeline |
|---|---|---|
| Core pattern | `while True: call_llm(); if tool_calls: invoke(); else: break` | `Pipeline.add_component() + connect() + run()` with Agent component |
| Data flow | Explicit variable passing in Python | Typed socket connections between components |
| Tool definition | Function + JSON schema | `Tool`, `@tool`, `ComponentTool`, `Toolset` |
| Model switching | Change API call parameters | Swap `ChatGenerator` component |
| RAG integration | Custom retrieval code | Built-in `Retriever` + `DocumentStore` components |
| Serialization | None (or custom) | YAML out of the box |
| Type safety | Runtime only | Build-time socket validation |
| Deployment | Custom HTTP server | Hayhooks |
| Overhead | Minimal | Framework + abstractions |
| Flexibility | Maximum (it's just Python) | Constrained by component protocol |
| Debugging | Standard Python debugging | Pipeline-specific tools (tracing, visualization) |
| Lines of code (simple agent) | ~50 | ~100-200 |

### When Haystack Shines

- **Multi-step RAG pipelines** with retrieval, reranking, prompt construction, and generation
- **Hybrid retrieval** combining BM25 and semantic search
- **Production deployments** needing observability, serialization, and HTTP serving
- **Team environments** where pipeline YAML definitions serve as shared artifacts
- **Complex workflows** with branching, conditional routing, and multiple LLM calls

### When a Minimal Loop Is Preferable

- **Simple single-agent tool-calling** where the pipeline abstraction adds overhead without benefit
- **Rapid prototyping** where framework setup time exceeds the time saved
- **Custom control flow** that does not fit the pipeline/component model
- **Minimal dependency footprint** requirements

---

## Sources

- [Haystack Documentation — Introduction](https://docs.haystack.deepset.ai/docs/intro)
- [Haystack Documentation — Pipelines](https://docs.haystack.deepset.ai/docs/pipelines)
- [Haystack Documentation — Pipeline Loops](https://docs.haystack.deepset.ai/docs/pipeline-loops)
- [Haystack Documentation — Components](https://docs.haystack.deepset.ai/docs/components)
- [Haystack Documentation — Custom Components](https://docs.haystack.deepset.ai/docs/custom-components)
- [Haystack Documentation — SuperComponents](https://docs.haystack.deepset.ai/docs/supercomponents)
- [Haystack Documentation — Agent](https://docs.haystack.deepset.ai/docs/agent)
- [Haystack Documentation — Agents](https://docs.haystack.deepset.ai/docs/agents)
- [Haystack Documentation — Tool](https://docs.haystack.deepset.ai/docs/tool)
- [Haystack Documentation — Retrievers](https://docs.haystack.deepset.ai/docs/retrievers)
- [Haystack Documentation — Document Store](https://docs.haystack.deepset.ai/docs/document-store)
- [Haystack Documentation — Serialization](https://docs.haystack.deepset.ai/docs/serialization)
- [Haystack Documentation — AsyncPipeline](https://docs.haystack.deepset.ai/docs/asyncpipeline)
- [Haystack Documentation — Choosing the Right Generator](https://docs.haystack.deepset.ai/docs/choosing-the-right-generator)
- [Haystack Documentation — OpenAIChatGenerator](https://docs.haystack.deepset.ai/docs/openaichatgenerator)
- [Haystack Documentation — AnthropicChatGenerator](https://docs.haystack.deepset.ai/docs/anthropicchatgenerator)
- [Haystack Tutorial — Building a Tool-Calling Agent](https://haystack.deepset.ai/tutorials/43_building_a_tool_calling_agent)
- [Haystack Cookbook — Tools Support](https://haystack.deepset.ai/cookbook/tools_support)
- [Haystack Blog — Haystack 2.0 Release](https://haystack.deepset.ai/blog/haystack-2-release)
- [GitHub — deepset-ai/haystack](https://github.com/deepset-ai/haystack)
- [GitHub — Agent source code](https://github.com/deepset-ai/haystack/blob/main/haystack/components/agents/agent.py)
