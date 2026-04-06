# Claude Code Feature Comparison Review

**Reviewed:** 2026-04-06
**Reviewer:** Analysis of Claude Code source (Anthropic CLI) against micro-x-agent-loop-python
**Scope:** Feature-by-feature comparison of agent infrastructure patterns
**Status key:** `Done` · `Partial` · `Gap` · `Beyond` (micro-x exceeds Claude Code)

---

## Review Context

This document compares the agent infrastructure in Claude Code (Anthropic's official CLI agent, TypeScript/Ink) against micro-x-agent-loop-python. The goal is to identify validated patterns that micro-x already implements, gaps worth closing, and areas where micro-x goes further.

Source material: Claude Code source repository at `claude-code-source/src/`.

---

## Feature Comparison

### 1. Task System

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Done** — both implement this |
| **Statuses** | `pending`, `in_progress`, `completed` | `pending`, `in_progress`, `completed` |
| **Dependencies** | `blocks` / `blockedBy` bidirectional edges | `blocks` / `blockedBy` bidirectional edges |
| **Ownership** | Agent auto-assigned on `in_progress`; cleared on agent shutdown | Agent status tracking; task claiming with 5 safety checks |
| **Lifecycle hooks** | `TaskCreated`, `TaskCompleted` hook events fired as shell commands | `taskCreatedHooks`, `taskCompletedHooks` (blocking, with error rollback) |
| **Storage** | File-backed JSON (`~/.claude/tasks/{listId}/{taskId}.json`) with lockfile | SQLite (`tasks.db`, session-scoped) |
| **Auto-cleanup** | All-complete triggers 5s hide timer then `resetTaskList()` | No auto-cleanup |
| **Code locations** | `src/utils/tasks.ts`, `src/tools/TaskCreateTool/`, `src/tools/TaskUpdateTool/` | `src/micro_x_agent_loop/tasks/manager.py`, `tasks/store.py`, `tasks/models.py` |
| **Micro-x note** | Micro-x's SQLite store and atomic claiming are arguably more robust than file-based JSON with lockfiles. |

---

### 2. Context Compaction

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Done** — both implement this |
| **Strategies** | Full compact, micro-compact (mid-turn), memory-aware compact, auto-compact | `NoneCompactionStrategy`, `SummarizeCompactionStrategy` |
| **Cheap model** | Uses same model | Dedicated `CompactionModel` (Haiku at ~8% of Sonnet cost) |
| **Trigger** | Auto-triggered approaching context limit; also manual `/compact` | Configurable token threshold (`CompactionThresholdTokens`); manual `/compact [tail N]` |
| **Post-compact** | `postCompactCleanup.ts` restores state (file history, attribution) | Message archival to SQLite for history preservation |
| **Code locations** | `src/services/compact/compact.ts`, `microCompact.ts`, `autoCompact.ts` | `src/micro_x_agent_loop/compaction.py` |
| **Gap in micro-x** | No micro-compact (mid-turn compaction) or memory-aware compaction variant. |
| **Micro-x advantage** | Dedicated cheap model for compaction saves 70-90% on compaction calls. |

---

### 3. Memory / Persistence System

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Partial** — micro-x has session memory but not typed cross-session memory |
| **Typed memories** | 4 types: `user`, `feedback`, `project`, `reference` — each with frontmatter schema | No typed memory categories |
| **Storage** | Individual markdown files with frontmatter + `MEMORY.md` index (200-line cap) | SQLite session store; `save_memory` MCP tool writes to filesystem |
| **Relevance scanning** | `findRelevantMemories.ts` filters by description match | No relevance-based retrieval |
| **Cross-session** | Memories persist in `~/.claude/projects/` and are loaded into context automatically | Session data persists in SQLite; no automatic cross-session memory injection |
| **Team memory** | `teamMemPaths.ts`, `teamMemPrompts.ts`, `teamMemorySync/` service | Not implemented |
| **Code locations** | `src/memdir/memdir.ts`, `findRelevantMemories.ts`, `memoryScan.ts` | `src/micro_x_agent_loop/memory/store.py`, `session_manager.py` |
| **Gap in micro-x** | Claude Code's typed memory (user preferences, feedback corrections, project context, external references) with automatic relevance filtering is a significant pattern not yet in micro-x. Plans exist: `PLAN-cross-session-user-memory.md`, `PLAN-claude-style-memory.md`. |

---

### 4. Session Management

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Done** — both implement this |
| **Resume** | `--continue` restores full conversation | `/session resume` restores from SQLite |
| **Fork** | `--continue --fork-session` creates new ID with same history | Session fork supported |
| **Concurrent sessions** | `concurrentSessions.ts` with naming | Session listing and switching |
| **State restoration** | File history, attribution state, context-collapse commits | Messages, tool calls, checkpoints, cost metrics |
| **Code locations** | `src/utils/sessionRestore.ts`, `sessionStorage.ts`, `sessionStart.ts` | `src/micro_x_agent_loop/memory/session_manager.py`, `checkpoints.py` |
| **Micro-x advantage** | File checkpointing with per-file rewind (`/rewind`, `/checkpoint`) — Claude Code has no equivalent. |

---

### 5. Hook System (Lifecycle Events)

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Gap** — micro-x has task hooks only, not a general lifecycle hook system |
| **Event types** | ~20 events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PreCompact`, `PostCompact`, `Setup`, `SessionStart`, `SessionEnd`, `Stop`, `SubagentStart`, `SubagentStop`, `Notification`, `TaskCreated`, `TaskCompleted`, `ConfigChange`, `CwdChanged`, `FileChanged`, `InstructionsLoaded`, `PermissionDenied` |
| **Execution model** | Shell commands spawned as child processes; environment variables carry context; exit code controls flow | Task lifecycle hooks only (`taskCreatedHooks`, `taskCompletedHooks`) — blocking with rollback |
| **Configuration** | JSON settings with hook name, command, and event binding | Not configurable by users |
| **Code locations** | `src/utils/hooks.ts`, `src/utils/hooks/hooksConfigManager.ts`, `src/services/tools/toolHooks.ts` | Task hooks in `src/micro_x_agent_loop/tasks/manager.py` |
| **Gap in micro-x** | A general-purpose hook system would enable users to add guardrails, logging, audit trails, and custom automation without modifying agent core code. The shell-command-based approach is language-agnostic and composable. This is one of the most transferable patterns from Claude Code. |

---

### 6. Permission System

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Gap** — micro-x has no per-tool-call permission system |
| **Layered model** | Tool-level rules, per-command rules, mode-level policies (`default`/`bypass`/`auto`) | No permission layer |
| **Interactive approval** | User prompted to allow/deny each tool call; "allow once" vs "allow always" with rule persistence | Human-in-the-loop via `ask_user` but no tool-specific approval |
| **Tool-specific rules** | `bashPermissions.ts` — specific patterns for dangerous commands | No command-level filtering |
| **Code locations** | `src/types/permissions.ts`, `src/utils/permissions/PermissionRule.ts`, `src/hooks/toolPermission/` | — |
| **Gap in micro-x** | Critical for any agent that takes real-world actions (file writes, API calls, shell commands). Claude Code's approach lets users build trust incrementally — start restrictive, allow more as confidence grows. The MCP mutation tracking (`PLAN-mcp-mutation-tracking.md`) is related but not the same as interactive approval. |

---

### 7. Plan Mode

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Gap** — micro-x has no plan mode |
| **Concept** | Agent proposes actions without executing; user approves/rejects before execution begins | Not implemented |
| **Entry/exit** | `EnterPlanModeTool` / `ExitPlanModeV2Tool` — model-initiated or user-initiated | — |
| **Verification** | `VerifyPlanExecutionTool` — approve/reject individual plan steps | — |
| **Code locations** | `src/tools/EnterPlanModeTool/`, `src/tools/ExitPlanModeTool/`, `src/utils/planModeV2.ts` | — |
| **Gap in micro-x** | Useful for high-stakes or ambiguous tasks where alignment matters before action. Would complement the existing `ask_user` HITL pattern. Lower priority than hooks and permissions. |

---

### 8. Sub-Agent / Teammate Spawning

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Done** — both implement this, different trade-offs |
| **Agent types** | Configurable from `.claude/agents/` directory; typed agents (`general-purpose`, `Explore`, `Plan`, etc.) | 3 types: `explore`, `summarize`, `general` |
| **Isolation** | Git worktree isolation (`isolation: "worktree"`) — agent gets its own repo copy | Isolated context windows (configurable `max_tokens`, `max_turns`, `timeout`) |
| **Execution** | Foreground (blocking) or background with notification; resume/fork capabilities | Parallel via `asyncio.gather`; no resume/fork |
| **Memory** | `agentMemory.ts`, `agentMemorySnapshot.ts` — agents can access/contribute to memory | Sub-agents have isolated context; no memory sharing |
| **Teams** | `TeamCreateTool`, `TeamDeleteTool` — create named teams with shared task lists | Not implemented |
| **Code locations** | `src/tools/AgentTool/AgentTool.tsx`, `runAgent.ts`, `resumeAgent.ts`, `forkSubagent.ts` | `src/micro_x_agent_loop/sub_agent.py` |
| **Gap in micro-x** | Worktree isolation, agent resume/fork, and team coordination are absent. Agent definition loading from config directory would be a clean addition. |

---

### 9. Tool System Architecture

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Done** — different approaches, both effective |
| **Tool definition** | Built-in TypeScript tools: `inputSchema` (Zod), `prompt()`, `call()`, `isEnabled()`, `isConcurrencySafe()` | MCP-based: all tools are external MCP servers; pseudo-tools for internal operations |
| **Deferred loading** | Tools registered by name, schemas fetched on demand via `ToolSearch` | Tool search with on-demand discovery (~500 tokens vs ~12,700 for full schema set) |
| **Parallel execution** | Supported with concurrency safety flags | `asyncio.gather` for parallel tool calls |
| **Code locations** | `src/Tool.ts`, `src/services/tools/toolExecution.ts` | `src/micro_x_agent_loop/tool.py`, `mcp/mcp_manager.py`, `mcp/mcp_tool_proxy.py` |
| **Micro-x advantage** | MCP-first design means zero tool code in the Python core — cleaner separation of concerns. Tool result formatting (json/table/text/key_value) is more sophisticated. |

---

### 10. Scheduling / Cron

| Attribute | Claude Code | micro-x |
|-----------|-------------|---------|
| **Status** | **Done** — micro-x goes further |
| **Cron parsing** | Custom 5-field parser with DST handling | `croniter` library |
| **Execution** | Lock-based coordination across sessions; recurring and one-shot | Always-on broker daemon; subprocess dispatch; overlap policies |
| **Persistence** | `.claude/scheduled_tasks.json` | SQLite (`broker.db`) with job and run tracking |
| **External triggers** | `RemoteTriggerTool` for remote agent management | Webhook endpoint + polling ingress for event-driven triggers |
| **HITL during scheduled runs** | Not supported | `broker_questions` table for HITL in autonomous runs |
| **Code locations** | `src/utils/cron.ts`, `cronScheduler.ts`, `src/tools/ScheduleCronTool/` | `src/micro_x_agent_loop/broker/service.py`, `scheduler.py`, `dispatcher.py` |
| **Micro-x advantage** | The broker daemon architecture is more capable: overlap prevention, webhook triggers, HITL support during autonomous runs, run history tracking. |

---

## Features Where micro-x Exceeds Claude Code

| Feature | Detail | Code location |
|---------|--------|---------------|
| **Semantic model routing** | Three-stage classifier (rules, keywords, LLM) routes tasks to optimal provider/model | `semantic_classifier.py`, `routing_strategy.py`, `task_taxonomy.py` |
| **Multi-provider LLM** | 5 providers (Anthropic, OpenAI, DeepSeek, Gemini, Ollama) with health tracking and fallback | `provider_pool.py`, `providers/` |
| **6-layer cost reduction** | Prompt caching, tool search, compaction, compiled mode, concise formatting, semantic routing | Multiple files; see `cost-reduction-review.md` |
| **API server (HTTP/WS)** | FastAPI with REST + WebSocket streaming; per-session agent lifecycle | `server/app.py`, `agent_manager.py`, `ws_channel.py` |
| **Voice mode** | Continuous STT via Deepgram with device selection and tuning | `voice_runtime.py`, `voice_ingress.py` |
| **File checkpointing** | Per-file rewind with checkpoint/restore commands | `memory/checkpoints.py` |
| **Broker daemon** | Always-on scheduler with webhook triggers, overlap policies, HITL in autonomous runs | `broker/service.py`, `scheduler.py` |
| **TUI** | Rich Textual interface with panels for tools, sessions, tasks, logs | `tui/app.py`, `tui/widgets/` |

---

## Priority Gaps to Address

Ordered by impact for a general-purpose agent:

| Priority | Gap | Why it matters | Effort estimate |
|----------|-----|----------------|-----------------|
| **1** | **Lifecycle hook system** | Enables guardrails, audit, logging, and user extensibility without core changes. Shell-command-based hooks are language-agnostic. | Medium — define events, config schema, and subprocess dispatch |
| **2** | **Permission system** | Any agent taking real-world actions needs incremental trust. Users must be able to approve/deny tool calls, with rules that persist. | Medium-high — requires UI integration (TUI modal), rule storage, and per-tool policy |
| **3** | **Typed cross-session memory** | User preferences, feedback corrections, and project context should survive across sessions and be automatically surfaced by relevance. Plans already exist (`PLAN-claude-style-memory.md`). | Medium — schema design, relevance scoring, and auto-injection into context |
| **4** | **Plan mode** | Propose-then-execute workflow for high-stakes tasks. Complements existing HITL. | Low-medium — state toggle, execution gating, verification step |
| **5** | **Agent resume/fork & team coordination** | Long-running sub-agents should be resumable. Team task lists enable multi-agent workflows. | Medium — requires sub-agent state persistence and shared task store |

---

## Summary

Micro-x-agent-loop-python implements **7 of 10** core Claude Code agent infrastructure patterns, and **exceeds Claude Code in 4 areas** (multi-provider routing, cost architecture, broker daemon, voice). The three significant gaps — lifecycle hooks, permissions, and typed memory — are all additive features that don't require rearchitecting existing systems. The existing protocol-based design (strategies, channels, providers) makes these natural extensions.
