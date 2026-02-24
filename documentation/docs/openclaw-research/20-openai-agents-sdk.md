# OpenAI Agents SDK

A lightweight, Python-first framework for building agents with tool use, handoffs, guardrails, and tracing. Evolved from OpenAI's experimental Swarm project.

## Core agent loop

The `Runner` class manages a deterministic run loop:

1. Call LLM with agent's model, settings, and accumulated messages
2. **Final output?** -> stop and return result
3. **Handoff?** -> replace current agent with target, restart from step 1
4. **Tool calls?** -> execute each, append results to history, restart from step 1

Loop continues until final output or `max_turns` exceeded (`MaxTurnsExceeded` exception). "Final output" depends on `output_type`: if set, loop runs until structured output matches that Pydantic type; otherwise, until plain text with no tool calls.

## Agent definition

```python
agent = Agent(
    name="Assistant",
    instructions="You are a helpful assistant",  # str or callable(RunContextWrapper) -> str
    model="gpt-4o",
    tools=[web_search_tool],
    handoffs=[specialist_agent],
    output_type=MyResponseModel,       # optional structured output
    input_guardrails=[check_relevance],
    output_guardrails=[check_safety],
    model_settings=ModelSettings(...),
    hooks=MyAgentHooks(),              # on_llm_start, on_llm_end
)
```

## Tool system

### Function tools
```python
@function_tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Sunny, 72F in {city}"
```
Auto-generates JSON schema from type hints and docstring. Pydantic validation of inputs/outputs.

### Hosted tools (OpenAI-managed, server-side)
- `WebSearchTool` — web search
- `FileSearchTool` — retrieval from Vector Stores
- `CodeInterpreterTool` — sandboxed Python execution
- `ImageGenerationTool` — image generation
- Computer Use — interact with computer interfaces

### MCP tools
Native support via `HostedMCPTool` (remote URL) or `mcp_servers` agent property (auto-aggregates tools from servers). Transports: Streamable HTTP, stdio.

## Handoffs

Primary multi-agent mechanism — **one-way transfer of control** between agents.

- Presented to LLM as tool calls (`transfer_to_refund_agent`)
- Full conversation state transfers with the handoff
- Current agent replaced by target, loop restarts

```python
triage = Agent(
    name="Triage",
    handoffs=[Handoff(
        agent=specialist,
        tool_name_override="escalate_to_specialist",
        on_handoff=my_callback,       # executed on handoff
        input_filter=my_filter_fn,    # filters history passed to next agent
        is_enabled=True,              # bool or callable for dynamic control
    )]
)
```

Decentralized peer-to-peer pattern — no central orchestrator. Each agent knows its handoff targets.

## Guardrails

Input/output validation with **fail-fast tripwire mechanism**.

- **Input guardrails**: Run on user's initial input (first agent only)
- **Output guardrails**: Run on agent's final response (last agent only)
- **Tool guardrails**: Wrap function tools, validate before/after execution

Execution modes:
- **Parallel** (default): Runs concurrently with agent — best latency, but agent may consume tokens before trip
- **Blocking**: Completes before agent starts — prevents wasted tokens

```python
@input_guardrail
async def check_relevance(ctx, agent, input):
    result = await Runner.run(guardrail_agent, input)
    return GuardrailFunctionOutput(
        output_info=result,
        tripwire_triggered=result.final_output.is_irrelevant
    )
```

## Context and memory

### RunContext
Custom context object passed through entire run. All tools, hooks, guardrails receive `RunContextWrapper[T]`.

### Session memory
- **`Session`**: Maintains conversation history across `Runner.run()` calls
- **`RedisSession`**: Distributed session memory across workers

### Server-side state
`previous_response_id` chains responses via OpenAI's Responses API.

## Tracing

Built-in automatic instrumentation:

- **Traces**: End-to-end operation of a workflow
- **Spans**: Individual operations (LLM call, tool execution, handoff, guardrail)
- **Custom spans**: `custom_span()` for application-specific tracking
- **Trace processors**: Register `TracingProcessor` implementations for custom export
- Integrates with Langfuse, LangSmith, and other observability platforms
- Feeds into OpenAI's evaluation and fine-tuning tools

## Streaming

`Runner.run_streamed()` returns async iterator of `StreamEvent`:

- **`RawResponsesStreamEvent`**: Token-by-token from LLM
- **`RunItemStreamEvent`**: Higher-level events (message created, tool called, handoff occurred)
- **`AgentUpdatedStreamEvent`**: Agent switch notification

## Runner execution

| Method | Type | Notes |
|--------|------|-------|
| `Runner.run()` | Async | Primary method |
| `Runner.run_sync()` | Sync | Won't work inside existing event loop |
| `Runner.run_streamed()` | Async streaming | Real-time token/event streaming |

## Comparison with other frameworks

| Dimension | OpenAI Agents SDK | LangGraph | AutoGen |
|-----------|-------------------|-----------|---------|
| Paradigm | Lightweight loop + handoffs | Stateful graph / FSM | Async multi-agent conversation |
| Orchestration | Decentralized peer-to-peer | Centralized graph edges | Message-passing |
| State | RunContext + Session | Graph state + checkpointing | Conversation-based |
| Control flow | Implicit (handoffs, tool calls) | Explicit (edges, conditional routing) | Conversation flow |
| Learning curve | Low (Python-native) | High (graph theory) | Medium |
| Guardrails | First-class with tripwires | Custom implementation | Custom validation |
| Tracing | Built-in span types | LangSmith integration | Basic logging |

## Key references

- [OpenAI Agents SDK docs](https://openai.github.io/openai-agents-python/)
- [GitHub: openai-agents-python](https://github.com/openai/openai-agents-python)
- [Framework comparison (Langfuse)](https://langfuse.com/blog/2025-03-19-ai-agent-comparison)
- [Detailed comparison (Turing)](https://www.turing.com/resources/ai-agent-frameworks)
