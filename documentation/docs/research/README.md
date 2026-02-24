# Agent Loop Architecture Research

Research notes exploring agent loop frameworks and patterns, gathered as reference material for the micro-x-agent-loop-python project.

## Documents

| Document | Framework | Focus |
|----------|-----------|-------|
| [langgraph-architecture.md](langgraph-architecture.md) | **LangGraph** (LangChain) | State-graph agent loops, checkpointing, streaming, human-in-the-loop, multi-agent supervisors |
| [crewai-architecture-research.md](crewai-architecture-research.md) | **CrewAI** | Multi-agent crews, role-based agents, ReAct loop, hierarchical orchestration, memory system |
| [deep-research-autogen-0.4.md](deep-research-autogen-0.4.md) | **AutoGen 0.4** (Microsoft) | Actor-model runtime, AgentChat API, group chat patterns, distributed agents, termination conditions |
| [pydantic-ai-agent-loop-architecture.md](pydantic-ai-agent-loop-architecture.md) | **Pydantic AI** | Type-safe agents, FSM-based loop, dependency injection, structured output, model abstraction |
| [claude-agent-sdk-architecture.md](claude-agent-sdk-architecture.md) | **Claude Agent SDK** (Anthropic) | CLI-backed agent loop, built-in tools, hooks/guardrails, subagents, MCP integration |
| [deep-research-compaction.md](deep-research-compaction.md) | *(cross-cutting)* | Token compaction strategies and context window management |

## Related

- [OpenClaw research](../openclaw-research/README.md) — separate deep-dive into the OpenClaw agent architecture

## Key Themes Across Frameworks

- **Loop pattern**: All frameworks implement some variant of the ReAct (Reason-Act-Observe) loop, differing mainly in how they model state transitions (explicit graph vs implicit loop vs FSM).
- **Tool dispatch**: Tool schemas are universally auto-generated from function signatures/type hints; execution is parallel where possible.
- **Memory/persistence**: Ranges from simple message history (Pydantic AI) to full checkpoint-and-replay (LangGraph) to multi-tier memory with semantic search (CrewAI, AutoGen).
- **Multi-agent**: Supervisor/manager patterns (LangGraph, CrewAI), group-chat orchestration (AutoGen), and subagent delegation (Claude Agent SDK) represent distinct coordination strategies.
- **Streaming**: All support token-level streaming; LangGraph and Pydantic AI offer the richest multi-mode streaming APIs.
- **Trade-off**: Every framework adds abstraction overhead in exchange for batteries-included features. A minimal custom loop trades those features for full transparency and control.
