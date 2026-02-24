# AutoGen (Microsoft)

AutoGen is a conversation-based multi-agent framework where agents communicate via asynchronous message passing. v0.4 re-architects around the **Actor Model**.

## Core architecture

### Layered design

- **Core (`autogen-core`)**: Scalable, event-driven actor framework — agent runtime, message routing, lifecycle management, distributed support
- **AgentChat (`autogen-agentchat`)**: High-level task-driven abstractions (recommended entry point)
- **Extensions (`autogen-ext`)**: Model clients, code executors, third-party integrations

### Communication model

Agents are "conversable" — any agent can send/receive messages to/from any other. v0.4 uses the Actor Model: each agent operates independently, maintains own state, communicates exclusively through async message passing. A centralized runtime handles delivery, enabling observability and decoupled architectures.

## Agent types

### v0.4 (current)
- **`AssistantAgent`**: LLM-powered, supports tool calling, structured output
- **`CodeExecutorAgent`**: Executes code (replaces v0.2 UserProxyAgent with execution)
- **`ToolUseAgent`**: Generates function calls, executes tools, reflects on results
- **Custom agents**: Implement `on_messages`, `on_reset`, `produced_message_types`

### v0.2 (legacy)
- **`AssistantAgent`**: LLM-powered with registered reply functions
- **`UserProxyAgent`**: Human bridge with `human_input_mode` (ALWAYS/TERMINATE/NEVER)
- **`GroupChatManager`**: Multi-agent speaker selection and routing

## Agent loop

### v0.2
Turn-by-turn via `initiate_chat` and `generate_reply`:
```
UserProxy sends message -> Assistant calls LLM -> reply -> UserProxy processes -> repeat
```
Continues until termination condition (TERMINATE keyword, max turns, custom).

### v0.4
Event-driven and async:
- Messages are typed dataclasses routed through Agent Runtime
- `RoutedAgent` base class with `@rpc` (request/response) and `@event` (fire-and-forget) decorators
- Teams manage turn-taking and termination
- `SingleThreadedAgentRuntime` for local dev; distributed runtime for production

## Tool/function calling

v0.4 tools wrapped in `FunctionTool`:
```python
tools = [FunctionTool(get_stock_price, description="Get stock price.")]
```

ToolUseAgent workflow: receive message -> generate function calls -> execute tools -> reflect on results -> return response.

## Group chat and orchestration

### Team types (v0.4)
- **`RoundRobinGroupChat`**: Fixed sequential order (A -> B -> C -> A...)
- **`SelectorGroupChat`**: LLM or custom function selects next speaker based on context
- **`Swarm`**: Self-organizing via `HandoffMessage` — agents decide to hand off to better-suited peers

### Advanced patterns
- **Router**: One agent receives requests, routes to specialists
- **Sequential pipeline**: Each agent outputs a type only the next can receive
- **Nested chats**: Hierarchical agent structures

### Termination conditions
`SourceMatchTermination`, `ExternalTermination`, `StopMessageTermination`, `MaxMessageTermination` — composable.

## Memory and state

- **Conversation history**: In-memory message history per agent
- **Jupyter executor**: Keeps kernel state across executions (avoids recomputation)
- **Save/restore (v0.4)**: Save and restore task progress, resume paused actions
- **State is agent-local**: No shared global state (actor model); communication is the only exchange mechanism
- No built-in long-term vector memory store — left to extensions

## Human-in-the-loop

- `UserProxyAgent` with `human_input_mode`: ALWAYS, TERMINATE, NEVER
- v0.4: Agent teams can pause for human review and resume upon approval
- Humans can approve actions, provide corrections, inject context, override decisions

## Code execution and sandboxing

- **Docker sandboxing by default** since v0.2.8 (`use_docker=True`)
- Docker container launched, code executed, container terminated
- **Jupyter executor**: Stateful execution maintaining kernel across runs
- **v0.4 extensions**: `DockerCommandLineCodeExecutor`, Azure Container Apps, Kubernetes
- Custom executors (e.g., E2B cloud sandboxes)

## Async execution model

v0.4 is async-first:
- All interactions use `async`/`await`
- Non-blocking — one agent can call an API while another operates in parallel
- Actor model enables distributed execution across processes/machines
- Cross-language interop (Python and .NET currently)

## v0.2 vs v0.4 changes

| Aspect | v0.2 | v0.4 |
|--------|------|------|
| Execution | Synchronous, blocking | Asynchronous, event-driven |
| Foundation | Direct function calls | Actor model, runtime-managed messages |
| Custom agents | Register `reply_func` callbacks | Implement `on_messages` etc. |
| Group chat | `GroupChat` + `GroupChatManager` | `RoundRobinGroupChat`, `SelectorGroupChat`, `Swarm` |
| State persistence | Not built-in | Save/restore, resume paused actions |
| Streaming | Not supported | Supported |
| Scalability | Single-process | Distributed agent runtime |

## Future: Microsoft Agent Framework

AutoGen and Semantic Kernel are converging into the **Microsoft Agent Framework** (GA targeted end of Q1 2026). Combines:
- AutoGen's simple agent abstractions
- Semantic Kernel's enterprise features (session state, type safety, middleware, telemetry)
- Graph-based workflows for multi-agent orchestration

AutoGen and Semantic Kernel enter maintenance mode (bug fixes only).

## Key references

- [GitHub: microsoft/autogen](https://github.com/microsoft/autogen)
- [AutoGen v0.4 announcement (Microsoft Research)](https://www.microsoft.com/en-us/research/blog/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/)
- [AutoGen 0.4 launch (DevBlogs)](https://devblogs.microsoft.com/autogen/autogen-reimagined-launching-autogen-0-4/)
- [CrewAI vs LangGraph vs AutoGen (DataCamp)](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen)
- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview)
