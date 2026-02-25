# DSPy Framework Architecture Research

> **Date**: 2026-02-24
> **Subject**: Stanford DSPy — "Programming, Not Prompting" Language Models
> **Repo**: [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy)
> **Docs**: [dspy.ai](https://dspy.ai/)
> **License**: MIT
> **Language**: Python (99.3%)
> **Version at time of research**: 3.1.3 (Feb 2026)
> **Stars**: ~32.4k

---

## 1. Overview

DSPy (Declarative Self-improving Python) is a framework from Stanford NLP that
treats LLM interactions as **optimizable programs** rather than hand-crafted prompt
strings. The core philosophy is "programming, not prompting" -- developers write
compositional Python code declaring *what* the system should do, and DSPy handles
the *how* of prompt generation, few-shot example selection, and weight tuning.

The research effort began at Stanford NLP in February 2022, building on compound
LM systems like ColBERT-QA, Baleen, and Hindsight. The first version shipped as
DSP in December 2022 and evolved into DSPy by October 2023.

### Three-Layer Architecture

DSPy is organized into three architectural layers:

| Layer | Purpose | Key Components |
|-------|---------|----------------|
| **Module Layer** | User-facing abstractions for defining tasks | `dspy.Module`, `dspy.Signature`, `dspy.Predict` |
| **Adapter Layer** | Runtime prompt formatting and response parsing | `ChatAdapter`, `JSONAdapter`, `XMLAdapter` |
| **Client Layer** | Unified LM interface, caching, retry, provider routing | `dspy.LM`, LiteLLM backend, 40+ providers |

### Data Flow

```
User Code
   |
Module.forward() / Module.__call__()
   |
Predict / ChainOfThought / ReAct  (inference strategy)
   |
adapter.format()  [signature + demos --> prompt]
   |
dspy.LM  [cache check --> LiteLLM --> provider API]
   |
adapter.parse()  [completion --> structured fields]
   |
dspy.Prediction  [typed output object]
   |
User receives result
```

### Installation

```bash
pip install dspy
```

---

## 2. Signatures

A **signature** is a declarative specification of the input/output behavior of a
DSPy module. Rather than writing prompt text, you declare *what* the module needs
to do.

### Inline (String) Signatures

The simplest form. Field names and optional types separated by `->`:

```python
# Basic question answering
"question -> answer"

# With explicit types (str is default)
"question: str -> answer: str"

# Typed output
"sentence -> sentiment: bool"

# Multiple fields
"context: list[str], question: str -> answer: str"

# Multiple outputs
"question, choices: list[str] -> reasoning: str, selection: int"
```

You can attach instructions to inline signatures:

```python
dspy.Signature(
    "comment -> toxic: bool",
    instructions="Mark as 'toxic' if comment includes insults, harassment..."
)
```

### Class-Based Signatures

For more complex tasks, inherit from `dspy.Signature`:

```python
class Emotion(dspy.Signature):
    """Classify emotion."""

    sentence: str = dspy.InputField()
    sentiment: Literal['sadness', 'joy', 'love', 'anger', 'fear', 'surprise'] = dspy.OutputField()
```

```python
class CheckCitationFaithfulness(dspy.Signature):
    """Verify that the text is based on the provided context."""

    context: str = dspy.InputField(desc="facts here are assumed to be true")
    text: str = dspy.InputField()
    faithfulness: bool = dspy.OutputField()
    evidence: dict[str, list[str]] = dspy.OutputField(desc="Supporting evidence grouped by claim")
```

### Typed Fields

- `dspy.InputField(desc=...)` -- declares an input parameter with optional description
- `dspy.OutputField(desc=...)` -- declares an output parameter with optional description

Supported types:
- Basic: `str`, `int`, `float`, `bool`
- Collections: `list[str]`, `dict[str, int]`
- Typing constructs: `Optional[float]`, `Union[str, int]`, `Literal[...]`
- Special DSPy types: `dspy.Image`, `dspy.History`
- Custom Pydantic models: any class extending `pydantic.BaseModel`
- Dot notation: `"query: MyContainer.Query -> score: MyContainer.Score"`

### Key Insight

The signature docstring becomes the LM instruction. Field descriptions become
prompt guidance. DSPy's adapters compile these declarations into provider-specific
prompt formats automatically.

---

## 3. Modules

DSPy modules are analogous to PyTorch's `nn.Module`. Each module abstracts a
**prompting technique** and is generalized to work with any signature. Modules
have learnable parameters (prompt instructions, demonstrations) and are callable.

### Built-In Modules

| Module | Purpose |
|--------|---------|
| `dspy.Predict` | Fundamental module. Directly implements a signature with no extra behavior. All other modules build on this. |
| `dspy.ChainOfThought` | Injects a `reasoning` field before the output, teaching the LM to think step-by-step. Drop-in replacement for `Predict` that often improves quality. |
| `dspy.ReAct` | Agent loop with tool integration. Implements Thought-Action-Observation cycle. See Section 4. |
| `dspy.ProgramOfThought` | Directs the LM to output executable code; execution results dictate the response. |
| `dspy.MultiChainComparison` | Compares multiple outputs from `ChainOfThought` to produce a final prediction. |
| `dspy.RLM` | Recursive Language Model that explores large contexts through a sandboxed Python REPL. |
| `dspy.CodeAct` | Code execution agent; LM generates code to accomplish the task. |
| `dspy.Refine` | Iterative refinement with automatic feedback loops (replaces `dspy.Assert`). |
| `dspy.BestOfN` | Runs module N times with different rollout IDs, returns best or first passing result. |

### Using Modules

```python
# Simple prediction
predict = dspy.Predict("question -> answer")
result = predict(question="What is the capital of France?")
print(result.answer)  # "Paris"

# Chain of thought (adds reasoning field automatically)
cot = dspy.ChainOfThought("question -> answer")
result = cot(question="What is 15% of 240?")
print(result.reasoning)  # step-by-step reasoning
print(result.answer)     # "36"

# With class-based signature
generate_answer = dspy.ChainOfThought(BasicQA)
pred = generate_answer(question="What is the color of the sky?")
```

### Module Composition via forward()

Custom modules inherit from `dspy.Module` and implement `forward()`:

```python
class MultiHop(dspy.Module):
    def __init__(self, num_hops=3):
        self.generate_query = dspy.ChainOfThought("context, question -> query")
        self.generate_answer = dspy.ChainOfThought("context, question -> answer")
        self.retrieve = dspy.Retrieve(k=3)
        self.num_hops = num_hops

    def forward(self, question: str) -> dspy.Prediction:
        context = []
        for _ in range(self.num_hops):
            query = self.generate_query(context=context, question=question).query
            passages = self.retrieve(query).passages
            context = deduplicate(context + passages)
        answer = self.generate_answer(context=context, question=question)
        return dspy.Prediction(context=context, answer=answer.answer)
```

### Configuration Options

Modules accept keyword arguments:
- `n=5` -- generate multiple completions
- `temperature=0.7` -- sampling temperature
- `max_len=500` -- maximum output length

Output is always a `dspy.Prediction` object with named fields.

---

## 4. ReAct Module (Agent Loop)

`dspy.ReAct` implements the Reasoning and Acting paradigm as a first-class DSPy
module. It provides a fully managed agent loop with tool execution.

### Constructor

```python
dspy.ReAct(
    signature: type[Signature],    # Input/output specification
    tools: list[Callable],         # Python functions or dspy.Tool instances
    max_iters: int = 20            # Maximum loop iterations
)
```

### The Thought-Action-Observation Loop

ReAct runs an iterative cycle:

1. **Thought Phase**: The LM generates `next_thought` -- reasoning about the current state.
2. **Action Phase**: The LM selects `next_tool_name` from available tools and provides `next_tool_args` as JSON.
3. **Observation Phase**: DSPy executes the selected tool and appends the result to the trajectory.
4. **Termination**: Loop ends when the special `finish` tool is selected or `max_iters` is reached.

After termination, a fallback extraction step processes the full trajectory to
produce the final output fields.

### Example Usage

```python
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"The weather in {city} is sunny, 72F."

def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Search results for: {query}"

react = dspy.ReAct(
    signature="question -> answer",
    tools=[get_weather, search_web],
    max_iters=5
)

pred = react(question="What is the weather in Tokyo?")
print(pred.answer)
```

### How It Differs from Hand-Written ReAct Loops

| Aspect | DSPy ReAct | Hand-Written Loop |
|--------|-----------|-------------------|
| **Prompt construction** | Automatic from signature + tool metadata | Manual prompt engineering |
| **Tool schema** | Auto-extracted from type hints + docstrings | Manually defined JSON schemas |
| **Error handling** | Built-in: errors formatted as observations | Must implement error catching |
| **Optimization** | Can be compiled with BootstrapFewShot/MIPRO to improve tool selection | Static prompts, manual tuning |
| **Trajectory management** | Automatic accumulation and context | Manual message list management |
| **Finish detection** | Built-in `finish` tool | Must implement stop conditions |
| **Portability** | Same code works across LM providers | Often tied to specific API formats |

### Native Function Calling

DSPy adapters support native function calling when available:
- `JSONAdapter` uses native calling by default
- `ChatAdapter` requires `use_native_function_calling=True`

This leverages the underlying LM's built-in tool calling capabilities rather than
text-based parsing.

---

## 5. Optimizers (Compilers)

DSPy's most distinctive feature: **automatic prompt optimization**. Rather than
hand-tuning prompts, you define a metric and let an optimizer search for better
prompts, demonstrations, and instructions.

### What Optimizers Tune

1. **Few-shot demonstrations** -- auto-generated examples included in prompts
2. **Natural language instructions** -- optimized prompt text for each module
3. **LM weights** -- fine-tuned model parameters (BootstrapFinetune)

### The Compilation Interface

All optimizers follow a consistent API:

```python
optimizer = SomeOptimizer(metric=your_metric, **config)
optimized_program = optimizer.compile(
    student=your_program,
    trainset=your_training_data
)
```

### Optimizer Catalog

#### BootstrapFewShot

Uses a teacher module to generate demonstrations. Validates results with your
metric, keeping only passing demonstrations.

```python
from dspy.teleprompt import BootstrapFewShot

optimizer = BootstrapFewShot(
    metric=your_metric,
    max_bootstrapped_demos=4,   # auto-generated examples
    max_labeled_demos=16,       # labeled examples from trainset
    max_rounds=1,
    max_errors=10
)
compiled = optimizer.compile(student=program, trainset=trainset)
```

With a custom teacher LM:

```python
optimizer = BootstrapFewShot(
    metric=your_metric,
    teacher_settings=dict(lm=gpt4)
)
```

#### BootstrapFewShotWithRandomSearch

Applies BootstrapFewShot multiple times with random search, selects the best
candidate program.

```python
from dspy.teleprompt import BootstrapFewShotWithRandomSearch

optimizer = BootstrapFewShotWithRandomSearch(
    metric=your_metric,
    max_bootstrapped_demos=2,
    num_candidate_programs=8,
    num_threads=4
)
compiled = optimizer.compile(student=program, trainset=trainset, valset=devset)
```

#### MIPROv2 (Multi-Instruction Prompt Optimizer)

The most sophisticated optimizer. Three-stage process:

1. **Bootstrapping**: Runs the program across inputs, collects high-scoring execution traces.
2. **Grounded Proposal**: Previews program code, data, and traces to draft many candidate instructions for every prompt.
3. **Discrete Search**: Uses Bayesian Optimization to find the best combination of instructions and demonstrations.

```python
from dspy.teleprompt import MIPROv2

optimizer = MIPROv2(
    metric=your_metric,
    auto="light"  # "light", "medium", or "heavy"
)
optimized = optimizer.compile(
    program.deepcopy(),
    trainset=trainset,
    max_bootstrapped_demos=3,
    max_labeled_demos=4,
)
```

Zero-shot (instructions only, no demonstrations):

```python
optimized = optimizer.compile(
    program.deepcopy(),
    trainset=trainset,
    max_bootstrapped_demos=0,
    max_labeled_demos=0,
)
```

#### Other Optimizers

| Optimizer | Description |
|-----------|-------------|
| `LabeledFewShot` | Simply selects k labeled examples from trainset |
| `COPRO` | Generates and iterates on prompt instructions |
| `KNNFewShot` | Uses nearest-neighbor retrieval to select relevant demonstrations per input |
| `BootstrapFewShotWithOptuna` | Uses Optuna for hyperparameter-style search |
| `SIMBA` | Stochastic Introspective Mini-Batch Ascent |
| `BootstrapFinetune` | Distills prompt-based programs into fine-tuned weights |
| `Ensemble` | Combines multiple candidate programs (e.g., via majority voting) |

### Optimizer Selection Guide

| Scenario | Recommended Optimizer |
|----------|-----------------------|
| ~10 labeled examples | `BootstrapFewShot` |
| 50+ examples | `BootstrapFewShotWithRandomSearch` |
| 0-shot optimization | `MIPROv2` (instruction-only mode) |
| 40+ trials, 200+ examples | `MIPROv2` (full mode) |
| 7B+ LM available for finetuning | `BootstrapFinetune` |

### Persistence

```python
optimized_program.save("./v1.json")

loaded = MyProgramClass()
loaded.load(path="./v1.json")
```

Saved files are readable JSON containing all parameters and generated content.

---

## 6. Tool / Function Integration

### Defining Tools

Tools are Python functions with type hints and docstrings. DSPy auto-extracts
metadata (name, parameter types, description) from these.

```python
def calculate_mortgage(principal: float, rate: float, years: int) -> str:
    """Calculate monthly mortgage payment given principal, annual rate, and term in years."""
    monthly_rate = rate / 100 / 12
    num_payments = years * 12
    payment = principal * (monthly_rate * (1 + monthly_rate)**num_payments) / \
              ((1 + monthly_rate)**num_payments - 1)
    return f"Monthly payment: ${payment:.2f}"
```

### The dspy.Tool Class

Wraps regular Python functions for DSPy compatibility:

```python
tool = dspy.Tool(calculate_mortgage)

tool.name       # "calculate_mortgage"
tool.desc       # docstring text
tool.args       # parameter schema dict
str(tool)       # full formatted description
```

### Integration Approaches

**Fully managed (ReAct)**:

```python
react = dspy.ReAct("question -> answer", tools=[calculate_mortgage, search_web])
```

**Manual tool handling** for fine-grained control:

```python
class ToolSignature(dspy.Signature):
    question: str = dspy.InputField()
    tools: list[dspy.Tool] = dspy.InputField()
    outputs: dspy.ToolCalls = dspy.OutputField()

tools = {
    "weather": dspy.Tool(weather),
    "calculator": dspy.Tool(calculator)
}

predictor = dspy.Predict(ToolSignature)
response = predictor(question="...", tools=list(tools.values()))

# Execute tool calls
for call in response.outputs.tool_calls:
    result = call.execute()  # auto function discovery
    # or: result = call.execute(functions={"weather": weather})
```

### Type Primitives

- `dspy.Tool` -- metadata representation of a callable function
- `dspy.ToolCalls` -- container for one or more tool invocations in a single turn
- `ToolCall.execute()` -- executes an individual tool call (v3.0.4b2+)

### Built-In Tools

- `PythonInterpreter` -- sandboxed Python expression execution
- `ColBERTv2` -- retrieval from indexed documents

### Async Tools

Use `acall()` for async functions, or enable `allow_tool_async_sync_conversion`
context for synchronous access to async tools.

### Adapter-Level Function Calling

Different adapters handle tool representations per provider:
- **OpenAI**: Native function calling with `tools` parameter
- **Anthropic**: Tool use with XML formatting
- **Local models**: Text-based tool descriptions with structured parsing

---

## 7. Evaluation

### Metric Functions

A metric is a Python function that scores program outputs:

```python
def metric(example, pred, trace=None) -> float | int | bool:
    """
    example: data instance from training/dev set
    pred:    output from the DSPy program (dspy.Prediction)
    trace:   optional, contains intermediate steps during optimization
    """
    return score
```

### Simple Metrics

```python
def validate_answer(example, pred, trace=None):
    return example.answer.lower() == pred.answer.lower()
```

Built-in: `answer_exact_match`, `answer_passage_match`.

### Multi-Dimensional Metrics

```python
def validate_context_and_answer(example, pred, trace=None):
    answer_match = example.answer.lower() == pred.answer.lower()
    context_match = any((pred.answer.lower() in c) for c in pred.context)

    if trace is None:  # evaluation mode
        return (answer_match + context_match) / 2.0
    else:  # bootstrapping mode (stricter)
        return answer_match and context_match
```

The `trace` parameter enables different behavior during optimization vs.
evaluation. When `trace is not None` (bootstrapping), you can impose stricter
checks so only high-quality examples become demonstrations.

### AI-Powered Metrics (LLM-as-Judge)

```python
class FactJudge(dspy.Signature):
    """Judge if answer is factually correct based on context."""
    context = dspy.InputField(desc="Context for the prediction")
    question = dspy.InputField(desc="Question to be answered")
    answer = dspy.InputField(desc="Answer for the question")
    factually_correct: bool = dspy.OutputField(
        desc="Is the answer factually correct based on context?"
    )

judge = dspy.ChainOfThought(FactJudge)

def factuality_metric(example, pred):
    factual = judge(
        context=example.context,
        question=example.question,
        answer=pred.answer
    )
    return factual.factually_correct
```

Advanced practice: the metric itself can be a DSPy program that gets compiled.

### The Evaluate Utility

```python
from dspy.evaluate import Evaluate

evaluator = Evaluate(
    devset=devset,
    metric=your_metric,
    num_threads=4,
    display_progress=True,
    display_table=5       # show top N rows
)
evaluator(your_program)
```

### Output Refinement (Replaces Assertions)

As of DSPy 2.6, `dspy.Assert` and `dspy.Suggest` are deprecated. They are
replaced by `dspy.Refine` and `dspy.BestOfN`:

**BestOfN** -- runs module up to N times with different rollout IDs, returns
the best prediction:

```python
def one_word_answer(args, pred):
    return 1.0 if len(pred.answer.split()) == 1 else 0.0

best = dspy.BestOfN(module=qa, N=3, reward_fn=one_word_answer, threshold=1.0)
result = best(question="Capital of Belgium?")
```

**Refine** -- like BestOfN but with automatic feedback generation between
attempts:

```python
refine = dspy.Refine(
    module=qa,
    N=3,
    reward_fn=one_word_answer,
    threshold=1.0,
    fail_count=1    # raise error after 1 failure (optional)
)
result = refine(question="Capital of Belgium?")
```

Both require a `reward_fn(args, pred) -> float` returning 0.0 to 1.0. They
stop when the threshold is met or N attempts are exhausted.

---

## 8. Model Abstraction

### dspy.LM

Unified interface for all language model providers, backed by LiteLLM:

```python
lm = dspy.LM(
    model="openai/gpt-4o",       # format: "provider/model_name"
    temperature=0.7,
    max_tokens=1000,
    cache=True,                   # response caching (default True)
    num_retries=3,
    # model_type="chat",          # "chat", "text", or "responses"
)
```

### Global Configuration

```python
dspy.configure(lm=lm)
```

Temporary overrides via context manager:

```python
with dspy.context(lm=another_lm):
    result = program(question="...")
```

Configuration precedence: instance-level > context manager > global settings.

### Supported Providers (via LiteLLM)

40+ providers including:
- `"openai/gpt-4o"`, `"openai/gpt-4o-mini"`, `"openai/o3"`
- `"anthropic/claude-sonnet-4-20250514"`
- `"together_ai/meta-llama/..."`, `"anyscale/..."`, `"ollama/..."`, etc.

### Reasoning Models

OpenAI reasoning models (o1, o3, o4, gpt-5) require special settings:

```python
lm = dspy.LM("openai/gpt-5", temperature=1.0, max_tokens=16000)
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `lm(prompt)` / `lm.acall(prompt)` | Forward pass (sync / async) |
| `lm.copy(**kwargs)` | Clone with updated parameters |
| `lm.inspect_history(n=1)` | View recent LM interactions |
| `lm.dump_state()` | Export config (excludes API keys) |
| `lm.finetune(...)` | Launch fine-tuning job |
| `lm.launch()` / `lm.kill()` | Manage model lifecycle |

### Caching

```python
# Disable caching globally
dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)

# Per-call cache bypass via rollout_id
predict(question="...", config={"rollout_id": 1, "temperature": 1.0})
```

### Usage Tracking

```python
dspy.configure(track_usage=True)
result = program(question="...")
print(result.get_lm_usage())  # token counts
```

### Streaming

```python
stream_predict = dspy.streamify(
    predict,
    stream_listeners=[
        dspy.streaming.StreamListener(signature_field_name="answer")
    ],
)

async for chunk in stream_predict(question="..."):
    print(chunk)
```

### Async Execution

```python
async_program = dspy.asyncify(program)
result = await async_program(question="...")
```

### Parallel Execution

```python
parallel = dspy.Parallel(num_threads=4)
results = parallel([
    (predict, dspy.Example(question="1+1").with_inputs("question")),
    (predict, dspy.Example(question="2+2").with_inputs("question")),
])
```

---

## 9. Comparison Notes: DSPy vs. Minimal Custom Agent Loop

### Where DSPy Excels

| Strength | Detail |
|----------|--------|
| **Automatic prompt optimization** | The compiler paradigm. Define a metric, provide examples, and DSPy searches for better prompts. No manual prompt engineering iteration. |
| **Portability** | Same program works across 40+ LM providers. Switch models by changing one string. |
| **Compositional modules** | Multi-hop RAG, chain-of-thought, tool use -- compose like software functions. Swap `Predict` for `ChainOfThought` in one line. |
| **Systematic evaluation** | Built-in `Evaluate` utility, metric functions, and optimization-evaluation loop. |
| **Few-shot management** | Automatic demonstration generation and selection. No manual few-shot example curation. |
| **Research-grade tooling** | MIPROv2, SIMBA, and other optimizers encode years of prompt optimization research. |

### Where DSPy Has Weaknesses

| Weakness | Detail |
|----------|--------|
| **Learning curve** | Requires understanding declarative programming, signatures, compilation. The abstraction cost is real. |
| **Abstraction overhead** | Prompt content is hidden behind adapters. Debugging exactly what prompt was sent requires `inspect_history()`. Less transparent than seeing the raw prompt. |
| **Limited multi-agent support** | Not designed for multi-agent orchestration. Single-agent ReAct loop is the primary agent pattern. |
| **Formatting fragility** | Output parsing depends on the adapter correctly parsing LM responses. Structured output failures can be opaque. |
| **Optimization requires data** | The compiler paradigm only helps if you have labeled examples and a metric. For exploratory/open-ended tasks, there is nothing to optimize. |
| **Observability tradeoffs** | Evaluation outcomes emphasized over low-level execution traceability. |
| **Agent loop simplicity** | ReAct module is a fixed Thought-Action-Observation cycle. Cannot easily customize the loop structure (e.g., add planning steps, self-reflection, custom retry logic). |

### The "Compile Prompts" Paradigm vs. Hand-Written Prompts

**DSPy approach**: You write `dspy.ChainOfThought("context, question -> answer")`
and provide 10+ training examples with a metric. DSPy's optimizer searches over
instruction variants and demonstration subsets to find the prompt that maximizes
your metric. The resulting prompt is auto-generated and may look nothing like
what a human would write.

**Hand-written approach**: You write the exact system prompt, tool descriptions,
and output format instructions. You iterate manually by running the agent,
inspecting failures, and editing the prompt. Full control and full visibility.

**Key tradeoff**: DSPy's compilation is powerful when you have (a) a measurable
metric, (b) representative training data, and (c) a task where the prompt
matters more than the architecture. For an open-ended coding agent or a tool-heavy
assistant where the loop structure and error recovery logic matter most, the
optimization target is the *code*, not the *prompt* -- and DSPy adds abstraction
without proportional benefit.

### Architectural Comparison

| Aspect | DSPy | Minimal Custom Loop |
|--------|------|---------------------|
| **Prompt authoring** | Declarative (signature + compilation) | Imperative (direct prompt strings) |
| **Agent loop** | Fixed ReAct pattern via `dspy.ReAct` | Fully custom while-loop with arbitrary logic |
| **Tool integration** | Auto-extracted from type hints/docstrings | Manually defined JSON schemas or function descriptions |
| **LM abstraction** | `dspy.LM` via LiteLLM (40+ providers) | Direct API client or LiteLLM |
| **Output parsing** | Adapter-based (Chat, JSON, XML adapters) | Manual JSON parsing or structured output |
| **Error recovery** | Observations fed back into trajectory | Custom retry/fallback logic |
| **Optimization** | Compiler-based (BootstrapFewShot, MIPRO, etc.) | Manual prompt iteration |
| **Evaluation** | `dspy.Evaluate` with metric functions | Custom evaluation scripts |
| **Complexity** | Higher -- framework concepts to learn | Lower -- just Python + API calls |
| **Flexibility** | Constrained to DSPy patterns | Unlimited |
| **Best for** | Eval-driven pipelines, RAG, classification | Exploratory agents, custom architectures |

### When to Choose DSPy

- You have a **measurable quality metric** and representative data
- You want to **systematically optimize** prompt quality rather than guess
- You are building **RAG pipelines** or **classification systems** where the prompt is the bottleneck
- You want **model portability** across providers without rewriting prompts
- You want to **experiment rapidly** with different prompting strategies (swap `Predict` for `ChainOfThought` for `ReAct`)

### When to Prefer a Custom Loop

- You need **full control** over the agent loop structure
- Your task is **open-ended** (no clear metric to optimize)
- You need **custom error recovery**, planning, or self-reflection steps
- **Transparency** matters -- you need to see and control every prompt
- You want **minimal dependencies** and a small codebase
- Multi-agent coordination is required

---

## References

- [DSPy GitHub Repository](https://github.com/stanfordnlp/dspy)
- [DSPy Official Documentation](https://dspy.ai/)
- [DSPy Signatures](https://dspy.ai/learn/programming/signatures/)
- [DSPy Modules](https://dspy.ai/learn/programming/modules/)
- [DSPy ReAct API](https://dspy.ai/api/modules/ReAct/)
- [DSPy Tools](https://dspy.ai/learn/programming/tools/)
- [DSPy Optimizers](https://dspy.ai/learn/optimization/optimizers/)
- [DSPy Metrics](https://dspy.ai/learn/evaluation/metrics/)
- [DSPy LM API](https://dspy.ai/api/models/LM/)
- [DSPy Cheatsheet](https://dspy.ai/cheatsheet/)
- [DSPy DeepWiki Overview](https://deepwiki.com/stanfordnlp/dspy/1-overview)
- [DSPy DeepWiki Tool Integration](https://deepwiki.com/stanfordnlp/dspy/3.3-tool-integration-and-react-agents)
- [DSPy Output Refinement](https://dspy.ai/tutorials/output_refinement/best-of-n-and-refine/)
- [Building AI Agents with DSPy](https://dspy.ai/tutorials/customer_service_agent/)
- [MIPROv2 API](https://dspy.ai/api/optimizers/MIPROv2/)
- [BootstrapFewShot API](https://dspy.ai/api/optimizers/BootstrapFewShot/)
- [Best AI Agent Frameworks 2025 Comparison](https://langwatch.ai/blog/best-ai-agent-frameworks-in-2025-comparing-langgraph-dspy-crewai-agno-and-more)
