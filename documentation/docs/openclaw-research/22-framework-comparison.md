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
| **Pattern** | Isolated agents with channel routing | Subagents via Task tool | Supervisor / swarm / hierarchical | Handoffs (peer delegation) + agents-as-tools (manager) | Conversation groups + swarm |
| **Communication** | Channel bindings + A2A send | Context isolation, announce back | Shared graph state | Handoff: full history (filterable); as_tool: isolated | Message passing |
| **Nesting** | 2 levels (maxSpawnDepth) | No recursion (1 level) | Unlimited (nested graphs) | Unlimited (bounded by `max_turns`) | Unlimited (nested chats) |
| **Concurrency cap** | 8 global, 5 per agent | Parallel subagents | Parallel super-step nodes | No cap (`asyncio.gather` or `parallel_tool_calls`) | Configurable |

## Sub-agent architecture deep comparison

Detailed comparison of how OpenClaw, Claude Code, and the OpenAI Agents SDK handle sub-agent delegation. See the full [three-way comparison](../research/comparison-subagents-claude-code-vs-openclaw.md) for code examples and architectural diagrams.

### Spawn and control flow

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Spawn mechanism** | `sessions_spawn` tool | `Task` tool with `subagent_type` | Handoff (LLM calls `transfer_to_<name>`) or `agent.as_tool()` |
| **Blocking** | Always async (fire-and-forget) | Foreground (blocking) or background | Synchronous within `Runner.run()` |
| **Who retains control** | Parent continues; result arrives via channel | Parent waits for summary | Handoff: target takes over; as_tool: parent retains |
| **Result delivery** | Announce step (normalized: status, result, notes, stats) | Free-form summary (tool result) | Handoff: last agent's output; as_tool: tool result (optionally typed) |

### Nesting and depth control

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Max depth** | Configurable 1-5 (`maxSpawnDepth`, default 1) | 1 (hard limit, Task denied for sub-agents) | Unlimited (bounded by `max_turns`, default 10) |
| **Circular delegation** | N/A (async, no return path) | Impossible (Task excluded) | Possible (A→B→A), bounded by `max_turns` |
| **Depth enforcement** | Config parameter + session tools denied by depth | Task tool excluded from sub-agent tool sets | `max_turns` global (handoff) or per-agent (`as_tool`) |
| **Orchestrator pattern** | Depth-1 agent with `sessions_spawn` access | Parent only | Handoff chains or nested `as_tool()` runs |

### Context and isolation

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Parent history** | Not inherited | Not inherited | Handoff: full history (default); as_tool: not inherited |
| **Context injection** | AGENTS.md + TOOLS.md (reduced bootstrap) | Task prompt only (fresh window) | Handoff: filterable history; as_tool: tool input string |
| **History filtering** | N/A | N/A | `input_filter`, `remove_all_tools`, `nest_handoff_history` |
| **Shared local state** | No | No | Handoff: yes (`RunContextWrapper`); as_tool: no |
| **System prompt** | Reduced (no SOUL.md/IDENTITY.md) | Agent-type-specific | Per-agent `instructions` field |

### Model selection

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Default** | Inherited from caller | Per agent type (Haiku for read-only, inherit for others) | Per-agent definition (no inheritance) |
| **Override** | `sessions_spawn.model` or config default | `model` param on Task call | `Agent(model=...)` on definition |
| **Built-in tiers** | No (config-driven) | Yes (Haiku/Sonnet/Opus per type) | No (any OpenAI model per agent) |

### Tool access

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Scoping** | Depth-based + per-agent allow/deny | Per agent type (hardcoded + custom allowlists) | Per agent definition (explicit `tools` list) |
| **Tool replacement** | N/A (isolated session) | N/A (isolated context) | Full replacement on handoff |
| **Runtime toggling** | N/A | N/A | `is_enabled` on tools and handoffs |
| **MCP scoping** | Per agent (config) | Per agent (SDK) | Per agent (`mcp_servers` field) |

### Concurrency

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Parallelism** | Async fire-and-forget | Multiple Task calls in one response | `asyncio.gather` or `parallel_tool_calls` |
| **Concurrency caps** | `maxConcurrent` (8) + `maxChildrenPerAgent` (5) | None | None |
| **Lifecycle** | Cascade stop + auto-archive (60 min) | Worktree auto-cleanup | None |

### Security and guardrails

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Model** | Multi-layer (tools + sandbox + exec approvals) | Mode-based (5 modes) + PreToolUse/PostToolUse hooks | Tripwire guardrails + `needs_approval` |
| **OS isolation** | Docker containers (network off, workspace ro/rw/none) | None (process-level) | None |
| **Guardrail scope** | All agents (plugin hooks) | All agents (hooks fire for sub-agents) | Input: first agent only; output: last agent only (unless `RunConfig`) |

### Tracing and observability

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Cross-agent tracing** | Stats in announce template | No built-in | Full trace with AgentSpan, HandoffSpan, GenerationSpan |
| **Trace linking** | Session key | N/A | `group_id` links separate `Runner.run()` calls |
| **Cost tracking** | Per-sub-agent in announce stats | ResultMessage at parent level | Per-`RunResult` usage fields |

### Architectural philosophy

| | OpenClaw | Claude Code | OpenAI Agents SDK |
|---|---|---|---|
| **Mental model** | **Process model** — async background workers with own lifecycle | **Function-call model** — sync, stateless, isolated, parent orchestrates | **Dual-pattern model** — handoffs (peer routing) + as_tool (manager orchestration) |
| **Best for** | Always-on daemon with multi-channel delivery | CLI coding assistant with specialized sub-tasks | Customer support routing, parallel analysis, structured workflows |
| **Structured I/O** | No | No | Yes (`input_type`, `parameters`, `output_type` with Pydantic) |

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
