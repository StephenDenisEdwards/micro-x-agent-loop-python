# smolagents Architecture Research

**Date:** 2026-02-24
**Subject:** Hugging Face smolagents — agent loop architecture, code agents, tool system
**Repo:** https://github.com/huggingface/smolagents
**Docs:** https://huggingface.co/docs/smolagents/en/index
**Version reviewed:** v1.24.0 (released 2026-01-16)
**License:** Apache-2.0
**Language:** Python
**PyPI:** `pip install smolagents`

---

## 1. Overview

smolagents is a minimalist, open-source Python library from Hugging Face for building LLM-powered agents. Its defining philosophy is **"agents that think in code"**: the default `CodeAgent` has the LLM write executable Python code to perform actions, rather than emitting JSON tool-call descriptions. The library is deliberately small — the core agent logic fits in roughly 1,000 lines of code in `agents.py`.

### Core design goals

- **Simplicity:** Minimal abstractions over raw code. The entire agent loop is transparent and inspectable.
- **Code-first agents:** `CodeAgent` generates Python snippets as actions, enabling natural composability (nesting, loops, conditionals, variable reuse).
- **Model-agnostic:** Any LLM — local Transformers, Hugging Face Inference Providers, OpenAI, Anthropic, Azure, AWS Bedrock, Ollama, 100+ providers via LiteLLM.
- **Tool-agnostic:** Tools from MCP servers, LangChain, Gradio Spaces on the Hub, or custom Python functions.
- **Hub integration:** Share and load agents and tools as Hub Spaces.
- **Sandboxed execution:** Secure code execution via LocalPythonExecutor (AST-based), E2B, Blaxel, Modal, Docker, or WebAssembly (Pyodide+Deno).

### Code agents vs tool-calling agents

smolagents provides two agent types that represent fundamentally different action paradigms:

| Dimension | CodeAgent | ToolCallingAgent |
|-----------|-----------|-----------------|
| **Action format** | Python code snippets | JSON tool-call objects |
| **Composability** | Native (nesting, loops, variables) | Limited (flat, one-call-at-a-time) |
| **Object management** | Natural (assign to variables) | Difficult (state references) |
| **Expressivity** | Arbitrary computation | Constrained to predefined tools |
| **Safety** | Requires sandbox | Inherently safer (no code exec) |
| **LLM training data** | Abundant Python in training corpora | Less tool-call JSON in corpora |
| **Predictability** | Less predictable outputs | More structured, validated outputs |

Research papers cited by the smolagents team (including "Executable Code Actions Elicit Better LLM Agents", 2024) show that code agents consistently outperform tool-calling agents on standard agentic benchmarks.

---

## 2. Agent Loop Lifecycle

All agents inherit from `MultiStepAgent`, which implements the ReAct (Reason + Act) framework from Yao et al., 2022. The loop is a multi-step cycle of reasoning, action, and observation.

### End-to-end flow of `agent.run(task)`

```
1. INITIALIZATION
   - System prompt -> SystemPromptStep (stored in agent.memory)
   - User task    -> TaskStep (appended to agent.memory.steps)

2. REACT LOOP (while not final_answer and step_count <= max_steps)
   a. agent.write_memory_to_messages()
      -> Converts memory steps into LLM-readable chat messages
      -> Injects tool descriptions, past actions, observations, errors, plans

   b. model.generate(messages)
      -> LLM produces a completion containing Thought + Action
      -> For CodeAgent: Thought text + Python code block
      -> For ToolCallingAgent: Thought text + JSON tool call(s)

   c. Parse the action
      -> CodeAgent: extract code between code block tags, parse AST
      -> ToolCallingAgent: parse JSON tool name + arguments

   d. Execute the action
      -> CodeAgent: run code in LocalPythonExecutor or remote sandbox
      -> ToolCallingAgent: call tool.forward(**arguments) or managed_agent

   e. Log result as ActionStep
      -> observations (stdout/return value), errors, timing, token counts
      -> Append ActionStep to agent.memory.steps

   f. Run step_callbacks
      -> User-defined callbacks with access to (memory_step, agent)

   g. (Optional) Planning step
      -> If planning_interval is set and step_number % planning_interval == 0
      -> LLM generates/updates a plan -> PlanningStep appended to memory

3. TERMINATION
   - CodeAgent: the LLM calls final_answer(result) in generated code
   - ToolCallingAgent: the LLM calls the final_answer tool
   - Or: max_steps reached -> agent.provide_final_answer() summarizes from logs
   - Optional: final_answer_checks validation functions run before accepting
```

### Pseudocode (from the blog)

```python
memory = [user_defined_task]
while llm_should_continue(memory):
    action = llm_get_next_action(memory)
    observations = execute_action(action)
    memory += [action, observations]
```

### Key parameters for `MultiStepAgent.__init__`

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `model` | `Model` | required | LLM engine |
| `tools` | `list[Tool]` | required | Available tools |
| `max_steps` | `int` | `20` | Maximum ReAct loop iterations |
| `planning_interval` | `int` | `None` | Steps between planning phases |
| `managed_agents` | `list` | `None` | Sub-agents callable as tools |
| `add_base_tools` | `bool` | `False` | Include default toolbox |
| `verbosity_level` | `LogLevel` | `INFO` | Logging detail level |
| `step_callbacks` | `list[Callable]` | `None` | Hooks called after each step |
| `instructions` | `str` | `None` | Custom instructions inserted in system prompt |
| `prompt_templates` | `PromptTemplates` | `None` | Custom prompt templates |
| `final_answer_checks` | `list[Callable]` | `None` | Validation functions for final answer |
| `return_full_result` | `bool` | `False` | Return `RunResult` object vs just answer |
| `name` | `str` | `None` | Required for managed agents |
| `description` | `str` | `None` | Required for managed agents |

### Streaming and step-by-step execution

`agent.run(task, stream=True)` returns a generator that yields each step as it executes. You can also drive the loop manually:

```python
agent.memory.steps.append(TaskStep(task=task, task_images=[]))
final_answer = None
step_number = 1
while final_answer is None and step_number <= 10:
    memory_step = ActionStep(step_number=step_number, observations_images=[])
    final_answer = agent.step(memory_step)
    agent.memory.steps.append(memory_step)
    step_number += 1
```

---

## 3. Code Agent Architecture

`CodeAgent` (subclass of `MultiStepAgent`, defined in `agents.py` line ~1489) is the flagship agent type. The LLM writes Python code as its action, which is then parsed and executed.

### How the LLM generates code

The system prompt instructs the model to produce output in a specific format:

```
Thought: <reasoning about the task and which tools to use>
Code:
```python
result = my_tool("argument")
print(result)
final_answer(result)
```<end_code>
```

The code block is extracted using configurable regex tags (`code_block_tags` parameter). By default these match Python code blocks; you can pass `"markdown"` to use triple-backtick fencing, or custom regex tuples.

### CodeAgent-specific parameters

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `additional_authorized_imports` | `list[str]` | `None` | Extra allowed imports |
| `executor_type` | `str` | `"local"` | `"local"`, `"e2b"`, `"blaxel"`, `"modal"`, `"docker"`, `"wasm"` |
| `executor` | `PythonExecutor` | `None` | Custom executor instance |
| `executor_kwargs` | `dict` | `None` | Extra args for executor init |
| `max_print_outputs_length` | `int` | `None` | Truncate stdout capture |
| `use_structured_outputs_internally` | `bool` | `False` | Use structured generation at each action step |
| `code_block_tags` | `tuple` or `"markdown"` | `None` | Regex tags for code extraction |

### LocalPythonExecutor

The default executor (`LocalPythonExecutor` in `local_python_executor.py`) is a custom Python interpreter built from scratch on top of the AST module. It does **not** use the standard `exec()`/`eval()` — instead it walks the AST node by node and executes operations individually.

**Security features:**

- **Import whitelist:** By default, only a safe list of imports is allowed: `statistics`, `numpy`, `itertools`, `time`, `queue`, `collections`, `math`, `random`, `re`, `datetime`, `stat`, `unicodedata`. Additional imports must be explicitly authorized via `additional_authorized_imports`.
- **Submodule access control:** Access to submodules is disabled by default. Each must be explicitly authorized (e.g., `numpy.random`), or use wildcard (`numpy.*`).
- **Operation cap:** Total elementary operations are capped (default: 1,000,000 iterations) to prevent infinite loops.
- **Undefined operations raise errors:** Any AST operation not explicitly implemented in the interpreter raises an `InterpreterError`.
- **Execution timeout:** Configurable via `timeout_seconds` parameter (default: `MAX_EXECUTION_TIME_SECONDS`).

**How tools are injected:**

Tools are sent into the executor's namespace via `executor.send_tools({**agent.tools})`. Each tool becomes a callable function in the code's execution scope. When the LLM writes `result = web_search("query")`, the `web_search` function is directly available in the namespace.

**Limitations:** No local sandbox can be 100% secure. A CVE (CVE-2025-9959) demonstrated a sandbox escape via incomplete dunder attribute validation. For production use, remote sandboxing is recommended.

### Remote Executors

All remote executors implement the `PythonExecutor` protocol with `run_code_raise_errors(code: str) -> CodeOutput` and `send_variables()`.

| Executor | Class | How it works |
|----------|-------|-------------|
| **E2B** | `E2BExecutor` | Cloud sandbox via e2b.dev; code sent to isolated container |
| **Blaxel** | `BlaxelExecutor` | VMs that hibernate/wake in <25ms; scales to zero |
| **Modal** | `ModalExecutor` | Cloud sandbox via modal.com |
| **Docker** | `DockerExecutor` | Jupyter kernel in local Docker container; resource-limited |
| **WebAssembly** | `WasmExecutor` | Pyodide + Deno runtime; binary-level isolation |

Usage pattern for all remote executors:

```python
with CodeAgent(model=model, tools=[], executor_type="e2b") as agent:
    agent.run("Calculate the 100th Fibonacci number")
# Sandbox is automatically cleaned up via context manager
```

**Important limitation:** Remote executors (approach 1: just sandboxing the code snippets) do not support multi-agent setups because managed agent calls require model calls, which need API credentials not transferred to the sandbox. For multi-agent with sandboxing, you must run the entire agentic system inside the sandbox (approach 2).

---

## 4. Tool System

### Defining tools

Tools are objects with metadata (name, description, input schema, output type) that the LLM can invoke. Two ways to define them:

#### `@tool` decorator (recommended for simple tools)

```python
from smolagents import tool

@tool
def visit_webpage(url: str) -> str:
    """Visits a webpage at the given URL and returns its content as markdown.

    Args:
        url: The URL of the webpage to visit.
    """
    import requests
    from markdownify import markdownify
    response = requests.get(url)
    return markdownify(response.text).strip()
```

Requirements:
- Clear function name (becomes the tool name)
- Type hints on all inputs and the return value
- Docstring with description and `Args:` section describing each parameter
- All imports must be inside the function body (for Hub sharing compatibility)

#### `Tool` subclass (for complex tools)

```python
from smolagents import Tool

class HFModelDownloadsTool(Tool):
    name = "model_download_counter"
    description = """Returns the most downloaded model for a given task on the Hub."""
    inputs = {
        "task": {
            "type": "string",
            "description": "the task category (e.g., text-classification)",
        }
    }
    output_type = "string"

    def forward(self, task: str):
        from huggingface_hub import list_models
        model = next(iter(list_models(filter=task, sort="downloads", direction=-1)))
        return model.id
```

Required class attributes:
- `name` (str) — tool name, used in system prompt and code namespace
- `description` (str) — instruction for the LLM
- `inputs` (dict) — keys are parameter names, values have `"type"` and `"description"`
- `output_type` (str) — Pydantic JSON Schema type: `"string"`, `"boolean"`, `"integer"`, `"number"`, `"image"`, `"audio"`, `"array"`, `"object"`, `"any"`, `"null"`
- `forward(self, **kwargs)` — the actual implementation

### How tools are injected into the agent

At initialization, tool attributes (name, description, inputs, output_type) are serialized and baked into the agent's **system prompt**. This gives the LLM a complete API reference for each available tool.

For `CodeAgent`: tools are additionally injected into the Python executor's namespace as callable functions. When the LLM generates `result = web_search("query")`, the executor resolves `web_search` to the tool's `forward()` method.

For `ToolCallingAgent`: tools are passed to the model via `tools_to_call_from` parameter in `model.generate()`. The model returns structured JSON tool calls which are then dispatched by `execute_tool_call(tool_name, arguments)`.

### Default toolbox (`add_base_tools=True`)

When smolagents is installed with `pip install 'smolagents[toolkit]'`:

- **DuckDuckGoSearchTool** / **WebSearchTool** — web search
- **PythonInterpreterTool** — code execution (added only to `ToolCallingAgent`, since `CodeAgent` already executes code natively)
- **Transcriber** — speech-to-text via Whisper-Turbo

### Managing tools at runtime

```python
agent.tools[model_download_tool.name] = model_download_tool  # Add
del agent.tools["some_tool"]                                   # Remove
```

`agent.tools` is a standard Python dictionary.

### Sharing tools via the Hub

```python
my_tool.push_to_hub("{username}/my-tool-name", token="...")
# Load:
from smolagents import load_tool
loaded_tool = load_tool("{username}/my-tool-name", trust_remote_code=True)
```

### Importing tools from other ecosystems

```python
# From LangChain
tool = Tool.from_langchain(langchain_tool)

# From a Gradio Space
tool = Tool.from_space("black-forest-labs/FLUX.1-schnell", name="image_gen", description="Generate images")
```

---

## 5. Multi-Agent System

smolagents supports hierarchical multi-agent orchestration. An agent can call other agents as if they were tools.

### How it works

1. Create a sub-agent with `name` and `description` attributes (mandatory).
2. Pass it to a manager agent via `managed_agents=[sub_agent]`.
3. The manager's system prompt is automatically updated with the sub-agent's name and description.
4. The manager can invoke the sub-agent by name (in code or JSON tool call).

```python
from smolagents import CodeAgent, ToolCallingAgent, InferenceClientModel, WebSearchTool

model = InferenceClientModel(model_id="Qwen/Qwen3-Next-80B-A3B-Thinking")

# Sub-agent: specialized web searcher
web_agent = ToolCallingAgent(
    tools=[WebSearchTool()],
    model=model,
    max_steps=10,
    name="web_search_agent",
    description="Runs web searches for you. Give it your query as an argument.",
)

# Manager agent: orchestrates and reasons
manager_agent = CodeAgent(
    tools=[],
    model=model,
    managed_agents=[web_agent],
    additional_authorized_imports=["time", "numpy", "pandas"],
)

answer = manager_agent.run("What is the population of France?")
```

### Design patterns

- **Manager = CodeAgent** (reasoning, planning, orchestration) + **Workers = ToolCallingAgent** (atomic tasks like web search).
- Each agent has its own memory and tool set, enabling specialization without cross-contamination.
- The `provide_run_summary` parameter controls whether a managed agent returns a full run summary to its manager.

### Prompt templates for managed agents

`ManagedAgentPromptTemplate` has two fields:
- `task` — prompt template for passing the task to the managed agent
- `report` — prompt template for how the managed agent reports back

### Serialization

`agent.save(output_dir)` saves:
- `agent.json` — agent configuration
- `prompt.yaml` — prompt templates
- `tools/` — one `.py` per tool
- `managed_agents/` — one folder per managed agent
- `app.py` — Gradio UI
- `requirements.txt` — detected dependencies

---

## 6. Model Abstraction

### Base class: `Model`

All model classes inherit from `Model` (in `models.py`). The key contract is the `generate()` method:

```python
class Model:
    def generate(
        self,
        messages: list[dict],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Tool] | None = None,
        **kwargs,
    ) -> ChatMessage:
        ...
```

Input: list of chat messages in `[{"role": "...", "content": "..."}]` format.
Output: `ChatMessage` object with `.content` attribute.

All model classes accept keyword arguments at initialization (`temperature`, `max_tokens`, `top_p`, etc.) that are forwarded to every completion call.

### Built-in model classes

| Class | Backend | Notes |
|-------|---------|-------|
| `InferenceClientModel` | `huggingface_hub.InferenceClient` | Default. Supports all HF Inference Providers (Cerebras, Cohere, Fireworks, Together, Nebius, Novita, SambaNova, Replicate, etc.). Default model: `Qwen/Qwen3-Next-80B-A3B-Thinking`. |
| `LiteLLMModel` | LiteLLM SDK | 100+ LLMs from any provider. `model_id` format: `"anthropic/claude-3-5-sonnet-latest"`, `"gpt-4o"`, `"ollama_chat/llama3.2"`. |
| `LiteLLMRouterModel` | LiteLLM Router | Load-balancing across multiple deployments with routing strategies, fallbacks, retries. |
| `OpenAIModel` | `openai` Python SDK | Any OpenAI-compatible API. Configurable `api_base`. |
| `AzureOpenAIModel` | `openai` (Azure) | Azure OpenAI deployments. Reads `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `OPENAI_API_VERSION`. |
| `AmazonBedrockModel` | `boto3` | Amazon Bedrock. Supports guardrail configs, cross-region inference. |
| `TransformersModel` | `transformers` pipeline | Local inference. Builds a pipeline for the given `model_id`. |
| `MLXModel` | `mlx-lm` | Apple Silicon local inference. |
| `VLLMModel` | `vllm` | High-throughput local serving. |

### Custom models

Subclass `Model` and implement `generate()`:

```python
class CustomModel(Model):
    def generate(self, messages, stop_sequences=None, **kwargs):
        response = my_api_call(messages, stop=stop_sequences)
        return ChatMessage(content=response.text)
```

### Rate limiting and retries

`ApiModel` (base for API models) supports `requests_per_minute` rate limiting and automatic retry on rate limit errors (configurable via `retry` parameter).

---

## 7. Memory and Planning

### Memory model: `AgentMemory`

The agent's memory is an `AgentMemory` object at `agent.memory`, containing:

- `system_prompt` (`SystemPromptStep`) — the agent's system prompt
- `steps` (`list[TaskStep | ActionStep | PlanningStep]`) — ordered list of all steps

#### Step types

| Step type | Purpose | Key fields |
|-----------|---------|------------|
| `SystemPromptStep` | System prompt | `system_prompt` |
| `TaskStep` | User's task | `task`, `task_images` |
| `ActionStep` | One ReAct iteration | `step_number`, `model_output`, `tool_calls`, `observations`, `observations_images`, `error`, `duration`, `input_token_count`, `output_token_count` |
| `PlanningStep` | Generated/updated plan | Plan text, facts |

### Memory -> Messages conversion

`agent.write_memory_to_messages()` serializes the step history into LLM chat messages. It:
- Includes the system prompt as a system message
- Converts each step into appropriate role messages
- Injects keywords (PLAN, ERROR, etc.) to help the LLM parse context
- Manages token budgets by selectively including/excluding content

### Planning

Controlled by the `planning_interval` parameter. When set (e.g., `planning_interval=3`):

- Every N steps, `agent.planning_step()` is called
- The method converts memory into an LLM prompt with past actions, observations, errors
- The LLM generates/updates a plan
- The plan is stored as a `PlanningStep` in memory
- On the first planning call, it generates an **initial plan** based on the task and available tools
- On subsequent calls, it **updates the plan** based on progress and new observations

Planning prompt templates are configurable via `PlanningPromptTemplate`:
- `plan` — initial plan generation prompt
- `update_plan_pre_messages` — context before memory for plan updates
- `update_plan_post_messages` — instructions after memory for plan updates

### Conversation continuity

`agent.run(task, reset=False)` preserves memory across multiple runs, enabling multi-turn conversations. With `reset=True` (default), memory is cleared between runs.

### Dynamic memory manipulation

Memory steps are directly accessible and mutable:

```python
# Access system prompt
agent.memory.system_prompt.system_prompt

# Iterate action steps
for step in agent.memory.steps:
    if isinstance(step, ActionStep):
        step.observations_images = None  # Remove images to save tokens

# Replay
agent.replay()  # Pretty-print all steps
agent.memory.get_full_steps()  # Full dict representation
agent.memory.get_succinct_steps()  # Summary representation
agent.memory.return_full_code()  # All code actions concatenated
```

### Step callbacks for memory management

Callbacks can dynamically modify memory at each step. Example: removing old screenshots from a web browser agent to save tokens:

```python
def update_screenshot(memory_step: ActionStep, agent: CodeAgent) -> None:
    for previous_step in agent.memory.steps:
        if isinstance(previous_step, ActionStep) and previous_step.step_number <= memory_step.step_number - 2:
            previous_step.observations_images = None  # Drop old images
    memory_step.observations_images = [new_screenshot]

agent = CodeAgent(tools=tools, model=model, step_callbacks=[update_screenshot])
```

---

## 8. MCP Integration

smolagents has first-class support for Model Context Protocol (MCP) tool servers, integrated since v1.4.1.

### MCPClient

The `MCPClient` class manages connections to MCP servers and exposes their tools:

```python
from smolagents import MCPClient, CodeAgent
from mcp import StdioServerParameters

# Stdio-based MCP server
server_params = StdioServerParameters(
    command="uvx",
    args=["--quiet", "pubmedmcp@0.1.3"],
    env={"UV_PYTHON": "3.12", **os.environ},
)

with MCPClient(server_params) as tools:
    agent = CodeAgent(tools=tools, model=model, add_base_tools=True)
    agent.run("Find latest research on COVID-19 treatment.")
```

```python
# Streamable HTTP-based MCP server
with MCPClient({"url": "http://127.0.0.1:8000/mcp", "transport": "streamable-http"}) as tools:
    agent = CodeAgent(tools=tools, model=model)
    agent.run("Get weather for Paris.")
```

### Multiple MCP servers

```python
with MCPClient([server_params1, server_params2]) as tools:
    agent = CodeAgent(tools=tools, model=model)
```

### ToolCollection.from_mcp

Alternative API via `ToolCollection`:

```python
from smolagents import ToolCollection

with ToolCollection.from_mcp(server_params, trust_remote_code=True) as tool_collection:
    agent = CodeAgent(tools=[*tool_collection.tools], model=model)
```

### Structured output support

MCP tools with `outputSchema` (per MCP spec 2025-06-18+) are supported:

```python
with MCPClient(server_params, structured_output=True) as tools:
    agent = CodeAgent(tools=tools, model=model)
```

When enabled:
- Tool JSON schemas are included in the CodeAgent system prompt
- `structuredContent` in MCP responses is automatically parsed
- The agent can reason about output structure before calling tools

### Transport protocols supported

- **Stdio** — local process via `StdioServerParameters`
- **Streamable HTTP** — remote server via `{"url": "...", "transport": "streamable-http"}`
- **SSE** (Server-Sent Events) — via URL dict

---

## 9. Additional Features

### Gradio UI

```python
from smolagents import GradioUI

ui = GradioUI(agent, file_upload_folder="uploads", reset_agent_memory=True)
ui.launch(share=True)
```

Provides an interactive chat interface. Under the hood, calls `agent.run(user_input, reset=False)` for each message.

### CLI

```bash
smolagent "Plan a trip to Tokyo" --model-type InferenceClientModel --model-id "Qwen/Qwen2.5-Coder-32B-Instruct" --tools web_search
smolagent  # Interactive mode
```

### Agent serialization

```python
agent.save("./my_agent")          # Save to folder
agent.push_to_hub("user/agent")   # Push to Hub
agent = CodeAgent.from_hub("user/agent", trust_remote_code=True)  # Load
agent = CodeAgent.from_folder("./my_agent")
agent_dict = agent.to_dict()       # Dict representation
agent = CodeAgent.from_dict(agent_dict)
```

### Instrumentation and observability

- `agent.logs` — fine-grained step-by-step logs
- `agent.replay()` / `agent.replay(detailed=True)` — pretty-printed replay
- `agent.visualize()` — Rich tree visualization of agent structure
- Integration with OpenTelemetry via `openinference-instrumentation-smolagents`
- `stream_to_gradio()` — stream agent steps as Gradio chat messages

---

## 10. Comparison Notes

### Strengths relative to a minimal custom agent loop

1. **Code agent paradigm is powerful.** Generating Python code as the action language is more expressive than JSON tool calls. It enables the LLM to compose tools, use loops, handle conditionals, and manage state naturally. Benchmarks show measurable improvements.

2. **Multiple sandbox options.** The tiered security model (local AST interpreter -> Docker -> E2B/Blaxel/Modal -> WebAssembly) provides flexibility for different risk profiles.

3. **Model abstraction is well-designed.** The `Model` base class with `generate()` contract makes it trivial to swap providers. The `InferenceClientModel` with Inference Providers is particularly convenient.

4. **First-class MCP support.** Native `MCPClient` with structured output support puts smolagents ahead of many frameworks for tool integration.

5. **Hub ecosystem.** Push/pull tools and agents as Spaces is a unique advantage tied to the Hugging Face ecosystem.

6. **Planning built-in.** The `planning_interval` mechanism with `PlanningStep` is a simple but effective planning integration.

7. **Genuine minimalism.** ~1,000 lines of core code is remarkably lean. The abstractions are shallow and the code is readable.

### Weaknesses / trade-offs

1. **Code execution risk.** Even with the AST-based executor, local code execution is inherently risky. The CVE-2025-9959 sandbox escape demonstrates this. Production use really requires remote sandboxing, which adds latency and infrastructure complexity.

2. **Limited conversation/session model.** Memory management is manual. There is no built-in token compaction, summarization, or eviction strategy — you must implement these via step callbacks.

3. **No structured output/schema enforcement.** The LLM's code output is parsed with regex, not grammar-constrained generation (though `use_structured_outputs_internally` is available as an opt-in).

4. **Multi-agent limitations with sandboxing.** Remote sandboxed execution (approach 1) does not support managed agents because model API keys cannot be transferred to the sandbox. This forces either local execution or running the entire system in the sandbox.

5. **No built-in token tracking/budget management.** While `ActionStep` records token counts, there is no automatic context window management or compaction.

6. **Experimental API.** The documentation explicitly states "smolagents is an experimental API which is subject to change at any time."

### Code-agent vs tool-call trade-off summary

For a minimal custom agent loop:
- If you need maximum reliability and safety, stick with JSON tool calling.
- If you need expressivity and the ability to compose tools, consider the code-agent approach but invest in sandboxing.
- The code-agent approach shines when the task requires multi-step computation, data transformation, or dynamic logic that would be awkward to express as a sequence of flat tool calls.
- The tool-calling approach is better for simple dispatch scenarios (call API A, then call API B) where predictability matters more than flexibility.

---

## Sources

- [smolagents documentation](https://huggingface.co/docs/smolagents/en/index)
- [smolagents GitHub repository](https://github.com/huggingface/smolagents)
- [smolagents on PyPI](https://pypi.org/project/smolagents/)
- [Introducing smolagents (blog post)](https://huggingface.co/blog/smolagents)
- [Secure code execution tutorial](https://huggingface.co/docs/smolagents/en/tutorials/secure_code_execution)
- [Tools tutorial](https://huggingface.co/docs/smolagents/en/tutorials/tools)
- [Memory management tutorial](https://huggingface.co/docs/smolagents/en/tutorials/memory)
- [Multi-agent orchestration example](https://huggingface.co/docs/smolagents/en/examples/multiagents)
- [ReAct conceptual guide](https://huggingface.co/docs/smolagents/en/conceptual_guides/react)
- [Agents API reference](https://huggingface.co/docs/smolagents/en/reference/agents)
- [Models API reference](https://huggingface.co/docs/smolagents/en/reference/models)
- [Guided tour](https://huggingface.co/docs/smolagents/en/guided_tour)
- [Hugging Face Agents Course — Code Agents](https://huggingface.co/learn/agents-course/en/unit2/smolagents/code_agents)
- [Hugging Face Agents Course — Tools](https://huggingface.co/learn/agents-course/en/unit2/smolagents/tools)
