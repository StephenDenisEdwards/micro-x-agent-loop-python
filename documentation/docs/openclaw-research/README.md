# OpenClaw Architecture Research

Research notes from an exploration of the [OpenClaw](https://github.com/openclaw/openclaw) codebase — a personal AI assistant you run on your own devices.

These documents cover the major subsystems of OpenClaw as reference material for designing and comparing agent loop architectures.

## Documents

| Document | Summary |
|----------|---------|
| [01-overview.md](01-overview.md) | Project overview and technology stack |
| [02-automation.md](02-automation.md) | Heartbeat, cron, hooks, webhooks, and Lobster workflows |
| [03-lobster-workflows.md](03-lobster-workflows.md) | Deterministic workflow runtime with approval gates |
| [04-agent-loop.md](04-agent-loop.md) | Agent loop lifecycle, streams, queueing, and hook points |
| [05-sessions-and-memory.md](05-sessions-and-memory.md) | Session management, memory files, and vector search |
| [06-storage.md](06-storage.md) | File system layout, persistence, and state management |
| [07-plugin-system.md](07-plugin-system.md) | Plugin architecture, registration API, slots, and distribution |
| [08-channel-system.md](08-channel-system.md) | Messaging channel architecture, routing, queueing, and adapters |
| [09-multi-agent.md](09-multi-agent.md) | Multi-agent routing, bindings, and per-agent configuration |
| [10-model-failover.md](10-model-failover.md) | Auth profile rotation, cooldowns, and model fallback chains |
| [11-system-prompt-and-context.md](11-system-prompt-and-context.md) | System prompt assembly, prompt modes, and context window |
| [12-sandboxing.md](12-sandboxing.md) | Docker sandbox modes, scopes, and workspace access levels |
| [13-sub-agents.md](13-sub-agents.md) | Sub-agent spawning, nesting, orchestrator pattern, and announce chain |
| [14-exec-and-approvals.md](14-exec-and-approvals.md) | Exec tool, approval policies, allowlists, and safe bins |
| [15-streaming.md](15-streaming.md) | Block streaming, chunking algorithm, and Telegram preview streaming |
| [16-gateway-protocol.md](16-gateway-protocol.md) | WebSocket protocol, roles, auth, device pairing, and network model |
| [17-browser-tool.md](17-browser-tool.md) | Browser automation via CDP, snapshots, ref system, and profiles |
| [18-claude-agent-sdk.md](18-claude-agent-sdk.md) | Claude Agent SDK: loop architecture, tools, subagents, sessions |
| [19-langgraph.md](19-langgraph.md) | LangGraph: graph-based orchestration, Pregel execution, checkpointing |
| [20-openai-agents-sdk.md](20-openai-agents-sdk.md) | OpenAI Agents SDK: lightweight loop, handoffs, guardrails, tracing |
| [21-autogen.md](21-autogen.md) | AutoGen: conversation-based multi-agent, actor model, group chat |
| [22-framework-comparison.md](22-framework-comparison.md) | Cross-cutting comparison of all five frameworks |

## Source Codebase

All references point to paths within the OpenClaw monorepo at `/root/openclaw`.

- **Runtime**: Node >= 22, TypeScript (ESM, strict mode)
- **Docs site**: [docs.openclaw.ai](https://docs.openclaw.ai)
- **Repo**: [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)
