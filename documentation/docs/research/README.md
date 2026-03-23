# Agent Loop Architecture Research

Research notes exploring agent loop frameworks and patterns, gathered as reference material for the micro-x-agent-loop-python project.

## Documents

| Document | Framework | Focus |
|----------|-----------|-------|
| [langgraph-architecture.md](langgraph-architecture.md) | **LangGraph** (LangChain) | State-graph agent loops, checkpointing, streaming, human-in-the-loop, multi-agent supervisors |
| [langgraph-multi-agent-deep-research.md](langgraph-multi-agent-deep-research.md) | **LangGraph** (LangChain) | Deep dive: subgraph composition, handoffs/Command, supervisor pattern, fan-out/Send, cross-agent checkpointing, Store memory |
| [crewai-architecture-research.md](crewai-architecture-research.md) | **CrewAI** | Multi-agent crews, role-based agents, ReAct loop, hierarchical orchestration, memory system |
| [deep-research-autogen-0.4.md](deep-research-autogen-0.4.md) | **AutoGen 0.4** (Microsoft) | Actor-model runtime, AgentChat API, group chat patterns, distributed agents, termination conditions |
| [pydantic-ai-agent-loop-architecture.md](pydantic-ai-agent-loop-architecture.md) | **Pydantic AI** | Type-safe agents, FSM-based loop, dependency injection, structured output, model abstraction |
| [claude-agent-sdk-architecture.md](claude-agent-sdk-architecture.md) | **Claude Agent SDK** (Anthropic) | CLI-backed agent loop, built-in tools, hooks/guardrails, subagents, MCP integration |
| [claude-code-subagent-architecture.md](claude-code-subagent-architecture.md) | **Claude Code** (Anthropic) | Sub-agent architecture: model selection, tool isolation, context boundaries, specialization |
| [comparison-subagents-claude-code-vs-openclaw.md](comparison-subagents-claude-code-vs-openclaw.md) | **Claude Code vs. OpenClaw vs. OpenAI Agents SDK vs. LangGraph** | Four-way comparison of sub-agent spawn, nesting, isolation, concurrency, security, tracing, and result delivery |
| [openai-agents-sdk-architecture.md](openai-agents-sdk-architecture.md) | **OpenAI Agents SDK** | Runner loop, handoffs, guardrails/tripwires, tracing, MCP, sessions |
| [openai-agents-sdk-multi-agent-deep-research.md](openai-agents-sdk-multi-agent-deep-research.md) | **OpenAI Agents SDK** | Deep dive: handoff mechanism, agents-as-tools, context/history transfer, nesting, concurrency |
| [smolagents-architecture.md](smolagents-architecture.md) | **smolagents** (Hugging Face) | Code agents vs tool-calling agents, AST-sandboxed execution, multi-agent, MCP |
| [dspy-architecture.md](dspy-architecture.md) | **DSPy** (Stanford) | Prompt-as-program paradigm, signatures, optimizers/compilers, ReAct module |
| [semantic-kernel-architecture.md](semantic-kernel-architecture.md) | **Semantic Kernel** (Microsoft) | Enterprise orchestration, plugins, agent framework, vector stores, filters |
| [openhands-architecture.md](openhands-architecture.md) | **OpenHands** (formerly OpenDevin) | Event-stream architecture, sandboxed coding agent, CodeActAgent, context condensation |
| [swe-agent-architecture.md](swe-agent-architecture.md) | **SWE-agent** (Princeton) | Agent-Computer Interface (ACI), constrained command set, SWE-bench evaluation |
| [haystack-architecture.md](haystack-architecture.md) | **Haystack 2.x** (deepset) | Pipeline-based DAG architecture, component system, agent-in-pipeline pattern |
| [deep-research-compaction.md](deep-research-compaction.md) | *(cross-cutting)* | Token compaction strategies and context window management |
| [gsd-context-engineering-framework.md](gsd-context-engineering-framework.md) | **GSD (Get Shit Done)** | Context isolation via subagent spawning, decompose→execute→verify workflow, wave-based parallel execution, applicability to compiled mode |
| [key-insights-and-takeaways.md](key-insights-and-takeaways.md) | *(synthesis)* | Key insights, best-in-class references, and practical lessons across all research |
| [local-model-hardware-options.md](local-model-hardware-options.md) | *(infrastructure)* | Local model inference: hardware options, cloud GPU pricing, qwen2.5:7b findings, cost comparison |

## Related

- [OpenClaw research](../openclaw-research/README.md) — separate deep-dive into the OpenClaw agent architecture

## Key Themes Across Frameworks

- **Loop pattern**: Most frameworks implement ReAct (Reason-Act-Observe), but with very different state models — explicit graphs (LangGraph), FSMs (Pydantic AI), pipelines (Haystack), actor messages (AutoGen), or compilable programs (DSPy).
- **Code agents vs tool agents**: smolagents highlights a fundamental split — agents can emit executable code (more expressive, composable) or structured tool-call JSON (safer, more predictable). SWE-agent's ACI shows that constraining the action space can boost performance significantly.
- **Tool dispatch**: Tool schemas are universally auto-generated from function signatures/type hints; execution is parallel where possible. Handoff-as-tool (OpenAI Agents SDK) is an emerging pattern.
- **Memory/persistence**: Ranges from simple message history (Pydantic AI) to full checkpoint-and-replay (LangGraph) to multi-tier memory with semantic search (CrewAI, AutoGen). Session/thread abstractions vary widely.
- **Multi-agent**: Supervisor/manager (LangGraph, CrewAI), group-chat orchestration (AutoGen), handoff chains (OpenAI Agents SDK), subagent delegation (Claude Agent SDK), and hierarchical code-agent managers (smolagents) represent distinct coordination strategies.
- **Sandboxing**: Coding agents (OpenHands, SWE-agent, smolagents) all invest heavily in execution isolation — Docker containers, E2B sandboxes, or AST-level interpreters.
- **Guardrails**: Tripwire patterns (OpenAI Agents SDK), hook chains (Claude Agent SDK), filters (Semantic Kernel), and task guardrails (CrewAI) show convergence on the need for interception points.
- **Enterprise vs minimal**: Semantic Kernel targets enterprise (.NET/Python/Java, plugin ecosystem, vector stores), while smolagents proves a capable agent can be ~1,000 lines. DSPy is orthogonal — it optimizes prompts rather than hand-coding loops.
- **Trade-off**: Every framework adds abstraction overhead in exchange for batteries-included features. A minimal custom loop trades those features for full transparency and control.
