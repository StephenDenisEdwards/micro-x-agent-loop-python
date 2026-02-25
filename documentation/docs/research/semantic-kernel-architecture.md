# Microsoft Semantic Kernel: Architecture Research

> **Date**: 2026-02-24
> **Subject**: Deep-dive into Microsoft Semantic Kernel's architecture, agent loop, plugin system, and enterprise features
> **Repo**: <https://github.com/microsoft/semantic-kernel>
> **License**: MIT
> **Languages**: C# (.NET), Python, Java
> **Stars**: ~27,300 (Feb 2026)

---

## 1. Overview

Semantic Kernel (SK) is Microsoft's open-source AI orchestration SDK. Its core philosophy is to serve as **lightweight middleware** that connects LLM capabilities with existing application code and enterprise services. Rather than replacing your codebase, SK wraps existing APIs and functions so that an LLM can discover and call them through function calling.

**Key characteristics:**
- Model-agnostic: supports OpenAI, Azure OpenAI, Hugging Face, Gemini, Claude, Mistral, and others
- Multi-language: .NET (primary), Python, and Java SDKs with feature parity goals
- Enterprise-focused: built-in telemetry, dependency injection, filters for responsible AI, and integration with Azure services
- Part of the broader **Microsoft Agent Framework** alongside AutoGen

**Tech stack (Python SDK):**
- Package: `semantic-kernel` on PyPI
- Requires Python 3.10+
- Async-first with `asyncio`
- Uses Pydantic for data models, `httpx` for HTTP
- Connectors for OpenAI, Azure OpenAI, Hugging Face, and more

**Key packages (.NET):**
- `Microsoft.SemanticKernel` (core)
- `Microsoft.SemanticKernel.Agents.Core` (ChatCompletionAgent)
- `Microsoft.SemanticKernel.Agents.OpenAI` (OpenAIAssistantAgent)
- `Microsoft.SemanticKernel.Agents.Orchestration` (multi-agent orchestration)
- `Microsoft.Extensions.VectorData.Abstractions` (vector store)

---

## 2. Kernel Architecture

The `Kernel` class is the central dependency injection container. It manages:
1. **AI services** (chat completion, embedding generation, text-to-image, etc.)
2. **Plugins** (collections of callable functions)
3. **Filters** (middleware for function invocation and prompt rendering)

### 2.1 Kernel Construction (Python)

```python
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.core_plugins.time_plugin import TimePlugin

# Create kernel
kernel = Kernel()

# Register an AI service
kernel.add_service(AzureChatCompletion(
    deployment_name="gpt-4",
    endpoint="https://my-endpoint.openai.azure.com/",
    api_key="..."
))

# Register a plugin
kernel.add_plugin(TimePlugin(), plugin_name="TimePlugin")
```

### 2.2 Kernel Construction (.NET)

```csharp
var builder = Kernel.CreateBuilder();
builder.AddAzureOpenAIChatCompletion(modelId, endpoint, apiKey);
builder.Services.AddLogging(c => c.AddDebug().SetMinimumLevel(LogLevel.Trace));
builder.Plugins.AddFromType<TimePlugin>();
Kernel kernel = builder.Build();
```

### 2.3 Kernel Construction (Java)

```java
Kernel kernel = Kernel.builder()
    .withAIService(ChatCompletionService.class, chatCompletionService)
    .withPlugin(lightPlugin)
    .build();
```

### 2.4 Key Kernel Methods (Python)

| Method | Purpose |
|--------|---------|
| `kernel.add_service(service)` | Register an AI service (chat, embedding, etc.) |
| `kernel.add_plugin(obj, plugin_name)` | Register a plugin from an object with `@kernel_function` methods |
| `kernel.add_function(plugin_name, function)` | Register a single function |
| `kernel.get_service(type=...)` | Retrieve a registered service by type |
| `kernel.invoke_prompt(prompt, arguments)` | Invoke a prompt with optional function calling |
| `kernel.invoke(function, arguments)` | Invoke a specific kernel function |
| `kernel.as_mcp_server(server_name)` | Export registered functions as an MCP server |
| `kernel.add_filter(filter_type, func)` | Register a filter (function invocation, prompt render, auto-function) |

### 2.5 Dependency Injection Pattern

In .NET, the Kernel follows the **Service Provider pattern**. Services are registered via `IServiceCollection`, and the Kernel is typically created as a **transient** service (it is lightweight -- just a container for services and plugins). This integrates naturally with ASP.NET DI:

```csharp
builder.Services.AddOpenAIChatCompletion(modelId: "gpt-4", apiKey: "...");
builder.Services.AddSingleton(() => new LightsPlugin());
builder.Services.AddTransient<Kernel>((sp) => {
    var plugins = sp.GetRequiredService<KernelPluginCollection>();
    return new Kernel(sp, plugins);
});
```

---

## 3. Agent Loop Lifecycle

Semantic Kernel's agent loop is driven by **function calling** -- the native capability of modern LLMs to request invocation of specific functions. SK automates the loop that would otherwise require manual implementation.

### 3.1 The Automatic Planning Loop

When automatic function calling is enabled, SK performs these steps internally:

1. **Schema generation**: Generates JSON schemas for all registered plugin functions
2. **Prompt assembly**: Combines chat history + function schemas into the LLM request
3. **LLM invocation**: Sends the request to the AI service
4. **Response parsing**: Determines if the response contains a text reply or function call(s)
5. **Function invocation**: If function calls are present, invokes the chosen functions with parsed arguments
6. **Result injection**: Adds function results to chat history as `tool` messages
7. **Re-invocation**: Sends updated chat history back to the LLM
8. **Loop termination**: Repeats steps 3-7 until the LLM produces a final text response or the maximum iteration count is reached

### 3.2 Enabling Auto Function Calling (Python)

```python
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings

execution_settings = AzureChatPromptExecutionSettings()
execution_settings.function_choice_behavior = FunctionChoiceBehavior.Auto()

result = await chat_completion.get_chat_message_content(
    chat_history=history,
    settings=execution_settings,
    kernel=kernel,
)
```

### 3.3 FunctionChoiceBehavior Options

| Behavior | Description |
|----------|-------------|
| `FunctionChoiceBehavior.Auto()` | LLM decides which functions to call; SK invokes them automatically |
| `FunctionChoiceBehavior.Auto(auto_invoke=False)` | LLM decides which functions to call; caller handles invocation manually |
| `FunctionChoiceBehavior.Required()` | Forces the LLM to call at least one function |
| `FunctionChoiceBehavior.None()` | Functions are described but the LLM is told not to call any |

### 3.4 Auto vs Manual Invocation

**Auto invocation** (default): SK handles the entire loop. Function calls are executed, results are appended to `ChatHistory`, and the LLM is re-called automatically. The caller receives only the final text response.

**Manual invocation** (`auto_invoke=False`): SK returns the raw function call requests (`FunctionCallContent` objects) to the caller. The caller must:
1. Add the assistant message (with function calls) to chat history
2. Invoke each function manually
3. Create `FunctionResultContent` objects and add them to chat history
4. Re-call the LLM with updated history

Manual invocation is useful for:
- Human-in-the-loop approval before function execution
- Custom error handling and retry logic
- Logging and auditing individual function calls
- Conditional function execution

### 3.5 Parallel Function Calling

When a model returns multiple function calls in a single response (parallel tool calling), SK handles them:
- **Default**: Invoked sequentially
- **Concurrent mode** (.NET): Set `FunctionChoiceBehaviorOptions.AllowConcurrentInvocation = true`
- **Python**: Multiple function calls from the model are invoked concurrently by default

### 3.6 Maximum Auto-Invoke Attempts

The `maximum_auto_invoke_attempts` setting controls how many function-calling round-trips are allowed before the loop terminates. This prevents infinite loops when the model keeps requesting function calls.

---

## 4. Plugin and Function System

Plugins are the primary extensibility mechanism in Semantic Kernel. A plugin is a named collection of `KernelFunction` objects that the LLM can discover and invoke.

### 4.1 KernelPlugin Class

`KernelPlugin` behaves like a dictionary with function names as keys and `KernelFunction` objects as values. It provides class methods to create plugins from:
- Python objects with `@kernel_function` decorated methods
- Directories containing `.py` files and YAML prompt files
- OpenAPI specifications
- MCP servers

### 4.2 Native Functions (Python)

```python
from semantic_kernel.functions import kernel_function
from typing import Annotated

class WeatherPlugin:
    @kernel_function
    async def get_weather(
        self,
        city: Annotated[str, "The city to get weather for"]
    ) -> str:
        """Gets the current weather for a city."""
        return f"The weather in {city} is sunny."
```

Key points:
- Decorate with `@kernel_function`
- Docstring becomes the function description (used by LLM for tool selection)
- Parameter types and `Annotated` descriptions become the JSON schema
- Functions can be sync or async
- Return type becomes part of the function metadata

### 4.3 Native Functions (.NET)

```csharp
public class WeatherPlugin
{
    [KernelFunction("get_weather")]
    [Description("Gets the current weather for a city")]
    public async Task<string> GetWeatherAsync(
        [Description("The city to get weather for")] string city)
    {
        return $"The weather in {city} is sunny.";
    }
}
```

### 4.4 Semantic Functions (Prompt-Based)

Semantic functions are defined as prompt templates rather than code. They use a template language with variable substitution:

```python
from semantic_kernel.prompt_template import InputVariable, PromptTemplateConfig

kernel.add_function(
    plugin_name="writer",
    function_name="summarize",
    prompt_template_config=PromptTemplateConfig(
        name="summarize",
        description="Summarizes the given text",
        template="Please summarize the following text:\n\n{{$input}}",
        input_variables=[
            InputVariable(
                name="input",
                description="The text to summarize",
                is_required=True,
            ),
        ],
    ),
)
```

Semantic functions can also be defined in YAML files:

```yaml
name: summarize
description: Summarizes the given text
template: |
  Please summarize the following text:
  {{$input}}
input_variables:
  - name: input
    description: The text to summarize
    is_required: true
```

### 4.5 OpenAPI Plugins

SK can import plugins directly from OpenAPI specifications, enabling any REST API to become callable by the LLM:

```python
kernel.add_plugin_from_openapi(
    plugin_name="petstore",
    openapi_url="https://petstore.swagger.io/v2/swagger.json"
)
```

### 4.6 MCP Server Plugins

SK can consume plugins from MCP (Model Context Protocol) servers:

```python
kernel.add_plugin_from_mcp(
    plugin_name="my_mcp",
    server_url="http://localhost:8000/sse"
)
```

And SK can **export** its registered functions as an MCP server:

```python
server = kernel.as_mcp_server(server_name="my_server")
```

### 4.7 Plugin Design Best Practices (from MS docs)

- Keep function count under 20 per API call (ideally under 10) for reliable tool selection
- Use descriptive function names and parameter names -- avoid abbreviations
- Provide detailed docstrings/descriptions only when needed to minimize token consumption
- Use primitive parameter types where possible
- Use local state for large/sensitive data -- pass IDs rather than full data through the LLM

---

## 5. Planners (Historical and Current)

### 5.1 Deprecated Planners

SK originally shipped dedicated planner classes. These are now **deprecated and removed** from all SDKs:

| Planner | Approach | Status |
|---------|----------|--------|
| **SequentialPlanner** | Generated a sequential plan as XML/JSON | Deprecated |
| **StepwisePlanner** | LLM-driven step-by-step reasoning | Deprecated |
| **HandlebarsPlanner** | Generated plans in Handlebars template syntax (loops, conditionals) | Deprecated |
| **FunctionCallingStepwisePlanner** | Added extra reasoning on top of function calling | Deprecated |

### 5.2 Why They Were Deprecated

Modern LLMs have native function calling built in (OpenAI 0613+, Claude, Gemini, Mistral). This makes dedicated planners redundant:
- Function calling provides the same capability natively
- Function calling is more reliable (model-native vs. prompt-engineered)
- Simpler developer experience
- Better cross-model compatibility

### 5.3 Current Approach: Function Calling as Planning

The current recommended approach is to use `FunctionChoiceBehavior.Auto()` which lets the LLM itself drive multi-step planning through iterative function calling. The LLM:
1. Receives the function schemas
2. Decides which functions to call and in what order
3. Observes results and decides next steps
4. Continues until the task is complete

This is equivalent to "planning" but driven natively by the model rather than by a separate planner component. The automatic loop in SK handles all the mechanics.

### 5.4 Handlebars Planner (Historical Detail)

Before deprecation, the Handlebars planner was notable for:
- Generating plans as Handlebars templates
- Supporting loops (`{{#each}}`) and conditionals (`{{#if}}`)
- Loading SK functions as Handlebars helpers
- Supporting 2-3x more functions than the older planners

### 5.5 FunctionCallingStepwise Planner (Historical Detail)

This planner added a reasoning step at the beginning of plan generation to improve reliability. It combined:
- Native function calling for execution
- Extra LLM reasoning for planning
- Better handling of complex multi-step tasks

---

## 6. Agent Framework

The Agent Framework is a higher-level abstraction built on top of the core Kernel. It provides structured agent types and multi-agent orchestration.

### 6.1 Agent Base Class

The abstract `Agent` class is the foundation. Key properties:
- `id`: Unique identifier
- `name`: Agent name
- `description`: Agent description
- `instructions`: System-level instructions (supports template variables)
- `kernel`: The underlying Kernel instance
- Agents can be invoked directly or composed into orchestrations

### 6.2 Agent Types

| Agent Type | Description | Backing Service |
|------------|-------------|-----------------|
| `ChatCompletionAgent` | Uses any SK chat completion service | Any supported LLM |
| `OpenAIAssistantAgent` | Uses OpenAI's Assistants API (stateful threads, file search, code interpreter) | OpenAI / Azure OpenAI |
| `AzureAIAgent` | Uses Azure AI Agent Service | Azure AI Foundry |
| `OpenAIResponsesAgent` | Uses OpenAI's Responses API | OpenAI |
| `CopilotStudioAgent` | Connects to Microsoft Copilot Studio agents | Copilot Studio |

### 6.3 ChatCompletionAgent (Python)

```python
from semantic_kernel.agents import ChatCompletionAgent

agent = ChatCompletionAgent(
    name="WeatherAssistant",
    instructions="You are a helpful weather assistant.",
    kernel=kernel,
    service_id="default",
)

# Direct invocation
thread = None
async for response in agent.invoke(messages="What's the weather in Seattle?"):
    print(response.content)
    thread = response.thread
```

### 6.4 AgentThread

The `AgentThread` abstraction manages conversation state:
- **Stateless agents** (ChatCompletionAgent): Thread manages chat history locally
- **Stateful agents** (OpenAIAssistantAgent, AzureAIAgent): Thread references server-side state via an ID
- Each agent type typically requires a matching thread type (e.g., `AzureAIAgent` requires `AzureAIAgentThread`)

### 6.5 Agent Orchestration Patterns

SK provides five built-in orchestration patterns (experimental as of Feb 2026):

#### Sequential Orchestration
Passes output from one agent to the next in a defined order:

```python
from semantic_kernel.agents.orchestration import SequentialOrchestration
from semantic_kernel.agents.runtime import InProcessRuntime

orchestration = SequentialOrchestration(members=[agent_a, agent_b])
runtime = InProcessRuntime()
runtime.start()
result = await orchestration.invoke(task="Write a blog post", runtime=runtime)
final_output = await result.get()
await runtime.stop_when_idle()
```

#### Concurrent Orchestration
Broadcasts a task to all agents and collects results independently:

```python
orchestration = ConcurrentOrchestration(members=[analyst_a, analyst_b, analyst_c])
```

#### Handoff Orchestration
Dynamically passes control between agents based on context or rules. Useful for escalation, fallback, or expert routing.

#### Group Chat Orchestration
All agents participate in a group conversation coordinated by a group chat manager. Useful for brainstorming, collaborative problem solving, and consensus building.

```python
orchestration = GroupChatOrchestration(
    members=[agent_a, agent_b, agent_c],
    manager=group_chat_manager
)
```

#### Magentic Orchestration
Inspired by Microsoft Research's MagenticOne. A generalist multi-agent collaboration pattern for complex tasks.

#### Unified Interface

All orchestration patterns share a consistent API:
1. Create orchestration with agents
2. Start a runtime (`InProcessRuntime`)
3. Invoke with a task
4. Await the result

### 6.6 Declarative Agent Specs (Experimental)

Agents can be defined via YAML specifications:

```python
from semantic_kernel.agents import register_agent_type, Agent, DeclarativeSpecMixin

@register_agent_type("custom_agent")
class CustomAgent(DeclarativeSpecMixin, Agent):
    ...
```

Custom agents can then be instantiated from YAML via `AgentRegistry.create_from_yaml(...)`.

### 6.7 Legacy: AgentGroupChat (Deprecated)

The older `AgentGroupChat` pattern has been superseded by the new `GroupChatOrchestration`. A migration guide is provided in the official docs.

---

## 7. Memory and Vector Store Connectors

### 7.1 Vector Store Abstraction

SK provides a model-first abstraction for interacting with vector databases. The abstraction is in RC status (release candidate) for .NET and preview for Python/Java.

**Core interfaces:**

| Interface | Purpose |
|-----------|---------|
| `VectorStore` | Cross-collection operations (list collections, get collection references) |
| `VectorStoreCollection<TKey, TRecord>` | Collection CRUD: create/delete collection, upsert/get/delete records, vector search |
| `IVectorSearchable<TRecord>` (.NET) / `VectorSearchBase` (Python) | Vector search capability |
| `VectorizableTextSearchMixin` | Search with auto-embedding by the database |
| `VectorizedSearchMixin` | Search with a pre-computed vector |

### 7.2 Data Model Definition (Python)

```python
from dataclasses import dataclass, field
from typing import Annotated
from semantic_kernel.data.vector import (
    DistanceFunction, IndexKind, VectorStoreField, vectorstoremodel,
)

@vectorstoremodel
@dataclass
class Hotel:
    hotel_id: Annotated[str, VectorStoreField('key')]
    hotel_name: Annotated[str, VectorStoreField('data', is_filterable=True)]
    description: Annotated[str, VectorStoreField('data', is_full_text_searchable=True)]
    description_embedding: Annotated[
        list[float],
        VectorStoreField('vector', dimensions=4,
                         distance_function=DistanceFunction.COSINE,
                         index_kind=IndexKind.HNSW)
    ]
    tags: Annotated[list[str], VectorStoreField('data', is_filterable=True)]
```

### 7.3 Data Model Definition (.NET)

```csharp
public class Hotel
{
    [VectorStoreKey]
    public ulong HotelId { get; set; }

    [VectorStoreData(IsIndexed = true)]
    public string HotelName { get; set; }

    [VectorStoreData(IsFullTextIndexed = true)]
    public string Description { get; set; }

    [VectorStoreVector(Dimensions: 4,
        DistanceFunction = DistanceFunction.CosineSimilarity,
        IndexKind = IndexKind.Hnsw)]
    public ReadOnlyMemory<float>? DescriptionEmbedding { get; set; }

    [VectorStoreData(IsIndexed = true)]
    public string[] Tags { get; set; }
}
```

### 7.4 Out-of-the-Box Connectors

| Connector | Package |
|-----------|---------|
| Azure AI Search | `semantic_kernel.connectors.azure_ai_search` |
| Azure Cosmos DB (MongoDB) | `semantic_kernel.connectors.azure_cosmos_db` |
| Qdrant | `semantic_kernel.connectors.qdrant` |
| Redis | `semantic_kernel.connectors.redis` |
| PostgreSQL (pgvector) | `semantic_kernel.connectors.postgres` |
| Elasticsearch | `semantic_kernel.connectors.elasticsearch` |
| Pinecone | `semantic_kernel.connectors.pinecone` |
| Weaviate | `semantic_kernel.connectors.weaviate` |
| ChromaDB | `semantic_kernel.connectors.chroma` |
| MongoDB Atlas | `semantic_kernel.connectors.mongodb_atlas` |
| In-Memory | `semantic_kernel.connectors.in_memory` |
| SQLite | `semantic_kernel.connectors.sqlite` |

### 7.5 RAG with Vector Stores

SK has built-in support for using vector stores for Retrieval Augmented Generation:

```python
# Create a search function from a collection
collection.create_search_function(
    function_name="hotel_search",
    description="Search hotels by description",
    search_type="vector",  # or "keyword_hybrid"
    string_mapper=lambda x: f"Hotel {x.record.hotel_name}: {x.record.description}",
)

# The search function can be added to the kernel as a plugin
# and used by agents via function calling
```

The `VectorSearchBase` is wrapped with `VectorizedSearchMixin`, `VectorizableTextSearchMixin`, or `VectorTextSearch` and exposed as a Text Search implementation compatible with the plugin system.

### 7.6 Legacy Memory Stores

Older "Memory Store" connectors (pre-vector store abstraction) are still available but deprecated. The new vector store abstraction is the recommended approach.

---

## 8. Filters and Hooks

SK provides three types of filters that act as middleware in the function/prompt execution pipeline. Filters are GA (generally available) in both .NET and Python.

### 8.1 Filter Types

| Filter Type | Trigger | Key Capabilities |
|-------------|---------|-----------------|
| **Function Invocation Filter** | Every `KernelFunction` invocation | Access/modify arguments, override results, handle exceptions, retry |
| **Prompt Render Filter** | Before prompt is sent to LLM | View/modify rendered prompt, implement semantic caching, PII redaction |
| **Auto Function Invocation Filter** | During auto function calling loop only | Access chat history, see all planned function calls, terminate the loop early |

### 8.2 Function Invocation Filter (Python)

```python
from semantic_kernel.filters import FunctionInvocationContext

@kernel.filter('function_invocation')
async def logging_filter(context: FunctionInvocationContext, next):
    print(f"Calling: {context.function.plugin_name}.{context.function.name}")
    await next(context)  # Must call next() to proceed
    print(f"Result: {context.result}")
```

Or using `add_filter`:

```python
async def logging_filter(context: FunctionInvocationContext, next):
    await next(context)

kernel.add_filter('function_invocation', logging_filter)
```

### 8.3 Prompt Render Filter (Python)

```python
from semantic_kernel.filters import FilterTypes, PromptRenderContext

@kernel.filter(FilterTypes.PROMPT_RENDERING)
async def prompt_filter(context: PromptRenderContext, next):
    await next(context)
    # Modify the rendered prompt before it's sent to the LLM
    context.rendered_prompt = sanitize_pii(context.rendered_prompt)
```

### 8.4 Auto Function Invocation Filter (Python)

```python
from semantic_kernel.filters import FilterTypes, AutoFunctionInvocationContext

@kernel.filter(FilterTypes.AUTO_FUNCTION_INVOCATION)
async def auto_func_filter(context: AutoFunctionInvocationContext, next):
    await next(context)
    # Terminate the auto-function-calling loop if we have our answer
    if "answer found" in str(context.function_result):
        context.terminate = True
```

### 8.5 Function Invocation Filter (.NET)

```csharp
public sealed class LoggingFilter : IFunctionInvocationFilter
{
    public async Task OnFunctionInvocationAsync(
        FunctionInvocationContext context,
        Func<FunctionInvocationContext, Task> next)
    {
        // Before
        logger.LogInformation("Calling {Plugin}.{Function}",
            context.Function.PluginName, context.Function.Name);

        await next(context);  // Proceed to next filter or function

        // After
        logger.LogInformation("Completed {Plugin}.{Function}",
            context.Function.PluginName, context.Function.Name);
    }
}

// Register via DI
builder.Services.AddSingleton<IFunctionInvocationFilter, LoggingFilter>();

// Or directly
kernel.FunctionInvocationFilters.Add(new LoggingFilter());
```

### 8.6 Filter Pipeline Behavior

- Calling `await next(context)` is **required** to proceed to the next filter or the actual operation
- **Not calling `next()`** prevents execution (useful for blocking malicious prompts)
- Filters execute in registration order
- The pipeline is like ASP.NET middleware: pre-processing, call next, post-processing
- Supports both streaming and non-streaming modes (`context.is_streaming` flag)

### 8.7 Enterprise Use Cases for Filters

| Use Case | Filter Type | Example |
|----------|-------------|---------|
| Logging / telemetry | Function Invocation | Log all function calls and durations |
| PII redaction | Prompt Render | Strip personal data before LLM call |
| Semantic caching | Prompt Render | Return cached response, skip LLM call |
| Content safety | Prompt Render | Block harmful prompts |
| Retry with fallback model | Function Invocation | Catch failure, switch to backup LLM |
| Human-in-the-loop | Auto Function Invocation | Pause for approval before tool execution |
| Early termination | Auto Function Invocation | Stop loop when desired result is found |
| Permission checks | Function Invocation | Verify user permissions before execution |

---

## 9. Comparison with a Minimal Custom Agent Loop

### 9.1 Strengths of Semantic Kernel

| Aspect | Detail |
|--------|--------|
| **Enterprise maturity** | Production-grade DI, telemetry, filter middleware, and Azure integration |
| **Multi-language** | Same concepts across .NET, Python, and Java -- good for polyglot teams |
| **Plugin ecosystem** | OpenAPI import, MCP server support, rich native plugin model |
| **Agent orchestration** | Built-in multi-agent patterns (Sequential, Concurrent, Handoff, GroupChat, Magentic) |
| **Vector store abstraction** | Unified API across 12+ vector databases with model-first schema definition |
| **Model agnostic** | Connectors for OpenAI, Azure OpenAI, Hugging Face, Google, Anthropic, Mistral, Ollama |
| **Function calling automation** | Full auto-invoke loop with parallel tool calling, error handling, and iteration limits |
| **Responsible AI** | Filters for PII redaction, content safety, permission checks, semantic caching |
| **MCP integration** | Both consumer and producer of MCP servers |

### 9.2 Weaknesses / Trade-offs

| Aspect | Detail |
|--------|--------|
| **Complexity** | Significant abstraction layers -- harder to understand control flow vs. a 200-line custom loop |
| **Overhead** | DI container, plugin registry, filter pipeline add overhead for simple use cases |
| **Learning curve** | Many concepts (Kernel, Plugin, Function, Filter, Agent, Thread, Orchestration, VectorStore) |
| **Opinionated structure** | Forces plugin-based function organization; not all code naturally maps to plugins |
| **.NET-first** | Python/Java SDKs sometimes lag behind .NET in feature completeness |
| **Rapid API changes** | Agent framework and orchestration patterns are still experimental with breaking changes |
| **Abstraction leakage** | Provider-specific settings (e.g., `OpenAIChatPromptExecutionSettings`) leak through the "model-agnostic" surface |
| **Token overhead** | Plugin metadata (function schemas, descriptions) consumes context window tokens |
| **Debugging difficulty** | Auto-invoke loop is a black box unless you add filters to observe intermediate steps |

### 9.3 When to Choose Each Approach

**Choose Semantic Kernel when:**
- Building enterprise applications that need DI, logging, and telemetry
- Working in a multi-language team (.NET + Python + Java)
- Need multi-agent orchestration patterns
- Need to integrate with Azure services and the Microsoft ecosystem
- Building production systems that require content safety, PII redaction, and auditing

**Choose a minimal custom agent loop when:**
- Simplicity and transparency are priorities
- You need full control over the tool-calling loop
- Token budget is tight and you want minimal schema overhead
- The application is small and doesn't need the full enterprise stack
- You want to understand exactly what's happening at every step
- Rapid prototyping without learning a large framework

### 9.4 Architecture Comparison

| Feature | Semantic Kernel | Minimal Custom Loop |
|---------|----------------|-------------------|
| Loop control | Automated by framework | Explicit in your code |
| Tool registration | `@kernel_function` decorator + plugin system | Dict/list of tool definitions |
| Tool dispatch | Automatic via plugin registry | Manual `match` on function name |
| Error handling | Filter middleware + auto-retry | Try/except in your loop |
| Conversation state | `ChatHistory` class | List of message dicts |
| Multi-agent | Built-in orchestration patterns | Build your own |
| Memory/RAG | Vector store abstraction + 12 connectors | Bring your own |
| Observability | Filter pipeline + OpenTelemetry integration | Custom logging |
| Token management | Not built-in (manual) | Manual |

---

## 10. Key Source Files and References

### Python SDK Structure
```
python/
  semantic_kernel/
    kernel.py                           # Kernel class
    functions/
      kernel_function.py                # @kernel_function decorator
      kernel_plugin.py                  # KernelPlugin class
    connectors/
      ai/
        open_ai/                        # OpenAI/Azure connectors
        function_choice_behavior.py     # FunctionChoiceBehavior
    contents/
      chat_history.py                   # ChatHistory
      chat_message_content.py           # ChatMessageContent
      function_call_content.py          # FunctionCallContent
      function_result_content.py        # FunctionResultContent
    agents/
      agent.py                          # Abstract Agent class
      chat_completion_agent.py          # ChatCompletionAgent
      orchestration/                    # Orchestration patterns
    filters/                            # Filter types and contexts
    data/
      vector/                           # Vector store abstractions
    prompt_template/                    # Prompt template system
```

### Key Documentation Links
- Overview: <https://learn.microsoft.com/en-us/semantic-kernel/overview/>
- Kernel: <https://learn.microsoft.com/en-us/semantic-kernel/concepts/kernel>
- Plugins: <https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/>
- Planning: <https://learn.microsoft.com/en-us/semantic-kernel/concepts/planning>
- Function Calling: <https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/function-calling/>
- Agent Framework: <https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/>
- Agent Architecture: <https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-architecture>
- Agent Orchestration: <https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/>
- Vector Stores: <https://learn.microsoft.com/en-us/semantic-kernel/concepts/vector-store-connectors/>
- Filters: <https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters>
- GitHub Repo: <https://github.com/microsoft/semantic-kernel>
- Python API Reference: <https://learn.microsoft.com/en-us/python/api/semantic-kernel/>
