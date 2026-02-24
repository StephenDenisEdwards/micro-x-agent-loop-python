# Framework Comparison

Cross-cutting comparison of agent loop architectures: OpenClaw, Claude Agent SDK, LangGraph, OpenAI Agents SDK, and AutoGen.

## Note on Moltbot

Moltbot (formerly Clawdbot) **is** OpenClaw — the project was renamed due to trademark concerns. The GitHub repo `moltbot/moltbot` redirects to `openclaw/openclaw`. Compatibility shims exist at `packages/moltbot/` and `packages/clawdbot/`.

**Moltworker** is a separate Cloudflare proof-of-concept that adapts OpenClaw to run on Cloudflare Workers (edge runtime + R2 storage + Browser Rendering). It's not an independent architecture — it wraps the same OpenClaw Gateway in a serverless deployment model.

## Loop architecture comparison

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Core pattern** | while(tool_call) with session lanes | while(tool_call) via CLI subprocess | Graph traversal (Pregel super-steps) | while(tool_call) with handoffs | Async message passing (actor model) |
| **Control flow** | Linear loop + queue modes | Linear loop + hooks | Declarative graph edges | Implicit (handoffs, tool calls) | Conversation-driven |
| **Concurrency** | Serialized per session lane | Parallel subagents | Parallel within super-steps | Sequential (single loop) | Async by default |
| **Language** | TypeScript (Node 22+) | Python/TS wrapping CLI | Python/JS | Python | Python/.NET |

## Tool systems

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Definition** | Plugin registration API | Built-in + MCP servers | `@tool` decorator + LangChain | `@function_tool` + hosted + MCP | `FunctionTool` wrapper |
| **Execution** | Gateway-managed, sandbox optional | CLI subprocess, sandboxed | ToolNode dispatches to functions | Runner executes inline | Agent-local execution |
| **Permission** | 8-9 layer allowlist pipeline | Hooks > rules > modes > callback | No built-in | Guardrails (tripwire) | No built-in |
| **Extensibility** | Plugin system (jiti) | MCP protocol (4 transports) | LangChain ecosystem | MCP + hosted tools | Extensions package |

## State and persistence

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Session storage** | JSONL transcript files | Session resume/fork via CLI | Checkpoints (SQLite/Postgres/Redis) | Session + RedisSession | In-memory (v0.4: save/restore) |
| **Long-term memory** | SQLite hybrid RAG (vector + BM25) | CLAUDE.md + filesystem | Cross-thread Store (namespaced KV) | RunContext (manual) | None built-in |
| **Compaction** | Auto-compaction with memory flush | Auto-compaction via API | Not needed (checkpoints) | Not built-in | Not built-in |
| **Context recovery** | Compaction + memory search | Progress files + git state | Load any checkpoint | Manual | Agent-local state |

## Multi-agent patterns

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Pattern** | Isolated agents with channel routing | Subagents via Task tool | Supervisor / swarm / hierarchical | Peer-to-peer handoffs | Conversation groups + swarm |
| **Communication** | Channel bindings + A2A send | Context isolation, announce back | Shared graph state | Full history transfer | Message passing |
| **Nesting** | 2 levels (maxSpawnDepth) | No recursion (1 level) | Unlimited (nested graphs) | Unlimited (handoff chains) | Unlimited (nested chats) |
| **Concurrency cap** | 8 global, 5 per agent | Parallel subagents | Parallel super-step nodes | Sequential | Configurable |

## Security and sandboxing

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Sandbox** | Docker containers (off/non-main/all) | Docker sandbox with network controls | None built-in | None built-in | Docker by default for code exec |
| **Approvals** | deny/allowlist/full + chat-forwarded | Permission modes + hooks | interrupt() / breakpoints | Guardrails with tripwires | UserProxyAgent + human_input_mode |
| **Tool policy** | Multi-layer pipeline per agent | Deny > allow > ask precedence | None built-in | Guardrails (input/output/tool) | None built-in |

## Streaming

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Approach** | Block streaming + chunking + coalescing | Async iterator + StreamEvent | 5 modes (values/updates/messages/events/custom) | 3 event types (raw/item/agent) | Basic (v0.4) |
| **Human pacing** | Optional randomized delay | N/A | N/A | N/A | N/A |
| **Channel-aware** | Per-channel text limits + chunk modes | N/A | N/A | N/A | N/A |

## Deployment model

| | OpenClaw | Claude Agent SDK | LangGraph | OpenAI Agents SDK | AutoGen |
|---|---|---|---|---|---|
| **Primary** | Self-hosted daemon (single Gateway) | Library (wraps CLI binary) | Library (open source) | Library (open source) | Library (open source) |
| **Production** | Docker Compose, Tailscale VPN | Any Python/Node runtime | LangGraph Server (task queues, scaling) | Any Python runtime | Distributed actor runtime |
| **Managed** | None (self-hosted only) | Via Anthropic API | LangGraph Cloud / BYOC | Via OpenAI API | Azure Container Apps |

## Philosophical differences

### OpenClaw: Personal assistant daemon
Optimized for always-on, multi-channel personal use. Channels, heartbeat, cron, and automation make it a daemon, not just a library. The agent is a persistent entity with identity and memory.

### Claude Agent SDK: Developer tool as library
Claude Code's internals exposed programmatically. Opinionated about tools (ships with file/bash/search built in). Best for software engineering workflows where the agent needs to read, edit, and test code.

### LangGraph: Workflow engine
Graph abstraction gives maximum control over execution flow. Best for complex branching workflows, pipelines with human gates, and systems requiring fault tolerance via checkpointing.

### OpenAI Agents SDK: Minimal abstractions
Four primitives (agents, handoffs, guardrails, tracing). Python-native with minimal framework overhead. Best for rapid prototyping and production systems that don't need complex orchestration.

### AutoGen: Conversation simulation
Agents as conversational participants. Natural for debate, peer review, and collaborative problem-solving. Moving toward Microsoft Agent Framework with enterprise features.

## When to use what

| Use case | Best fit |
|----------|----------|
| Personal AI assistant with chat integrations | OpenClaw |
| Software engineering automation | Claude Agent SDK |
| Complex branching workflows with checkpoints | LangGraph |
| Rapid prototyping with OpenAI models | OpenAI Agents SDK |
| Multi-agent debate / code generation with review | AutoGen |
| Production system needing fault tolerance | LangGraph or OpenClaw |
| Minimal dependencies, full transparency | Raw while-loop (no framework) |
