# GSD (Get Shit Done) — Context Engineering & Multi-Agent Orchestration Research

## Executive Summary

GSD (`get-shit-done-cc`, v1.22.4) is a **meta-prompting and context engineering system** for AI coding agents (Claude Code, OpenCode, Gemini CLI, Codex). It installs as an NPM package that injects slash commands into the agent runtime, providing a structured spec-driven development workflow.

The core thesis: AI agents suffer from **"context rot"** — quality degrades as the context window fills up. GSD solves this by decomposing work into atomic plans, each executed in a **fresh 200k-token context**, while a lightweight orchestrator manages state through structured markdown files.

GSD is a **prompt-only framework** — there is essentially no runtime code. The "application" is the LLM itself; GSD provides structured context via 32 slash commands, 12 agent prompt definitions, workflow templates, and a file-based state system. This is architecturally distinct from this project, which is a **runtime framework** with programmatic orchestration.

**Repository:** [github.com/gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)
**License:** MIT
**Last reviewed:** 2026-03-06 (v1.22.4)

---

## Architecture

### System Components

| Layer | Contents | Notes |
|-------|----------|-------|
| **32 slash commands** (`commands/gsd/`) | Markdown prompt files injected into the agent | Core interface — each command is a structured prompt |
| **12 agent definitions** (`agents/`) | Specialized agent prompts | researcher, planner, checker, executor, verifier, debugger, etc. |
| **Workflows** (`get-shit-done/workflows/`) | Multi-step orchestration logic | Prompt-based workflow coordination |
| **Templates** (`get-shit-done/templates/`) | File templates for state files | PROJECT.md, REQUIREMENTS.md, STATE.md, etc. |
| **Installer** (`bin/install.js`) | Node.js script | Copies commands into `~/.claude/commands/` or equivalent |
| **Hooks** (`hooks/`) | Git hooks | Atomic commit enforcement |

### Agent Specialization

GSD defines 12 agent types, all as markdown prompt files:

| Agent | Role |
|-------|------|
| `gsd-project-researcher` | Initial domain research |
| `gsd-phase-researcher` | Per-phase implementation research |
| `gsd-research-synthesizer` | Synthesize research findings |
| `gsd-planner` | Create atomic task plans |
| `gsd-plan-checker` | Verify plans against requirements |
| `gsd-roadmapper` | Create project roadmaps |
| `gsd-executor` | Implement tasks in isolated contexts |
| `gsd-verifier` | Confirm deliverables against goals |
| `gsd-debugger` | Diagnose failures |
| `gsd-codebase-mapper` | Analyze existing codebases (brownfield) |
| `gsd-integration-checker` | Verify integrations |
| `gsd-nyquist-auditor` | Audit milestone completeness |

### State Management — File-Based Context Anchors

GSD manages context through structured markdown files with enforced size limits:

| File | Purpose | Lifecycle |
|------|---------|-----------|
| `PROJECT.md` | Vision, goals, constraints | Created at init, always loaded |
| `REQUIREMENTS.md` | Scoped requirements with phase traceability | Created at init, referenced throughout |
| `ROADMAP.md` | Phases, progress, direction | Created at init, updated per phase |
| `STATE.md` | Decisions, blockers, current position | Updated continuously |
| `{N}-CONTEXT.md` | Per-phase design decisions | Created during discuss phase |
| `{N}-RESEARCH.md` | Per-phase research findings | Created during plan phase |
| `{N}-{M}-PLAN.md` | Atomic task plans (XML structured) | Created during plan phase |
| `{N}-{M}-SUMMARY.md` | Execution results | Created during execute phase |
| `{N}-VERIFICATION.md` | Phase verification results | Created during verify phase |
| `{N}-UAT.md` | User acceptance test results | Created during verify phase |

All stored under `.planning/` with git tracking.

---

## Core Workflow: The 5-Phase Loop

### Phase 1: Initialize (`/gsd:new-project`)

Interactive questioning → parallel research agents → requirements extraction → roadmap creation.

Creates the foundational state files (PROJECT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md).

### Phase 2: Discuss (`/gsd:discuss-phase N`)

Captures implementation decisions **before** planning. The system identifies gray areas based on what's being built (visual features → layout/density; APIs → response format/error handling; content → structure/tone). Answers go into `CONTEXT.md`, guiding both researcher and planner.

### Phase 3: Plan (`/gsd:plan-phase N`)

1. **Research** — investigates implementation approaches guided by CONTEXT.md
2. **Plan** — creates 2-3 atomic task plans with XML structure
3. **Verify** — checker agent validates plans against requirements; iterates until passing

Each plan uses a structured XML format:

```xml
<task type="auto">
  <name>Create login endpoint</name>
  <files>src/app/api/auth/login/route.ts</files>
  <action>
    Use jose for JWT. Validate credentials against users table.
    Return httpOnly cookie on success.
  </action>
  <verify>curl -X POST localhost:3000/api/auth/login returns 200 + Set-Cookie</verify>
  <done>Valid credentials return cookie, invalid return 401</done>
</task>
```

### Phase 4: Execute (`/gsd:execute-phase N`)

Plans grouped into **dependency-aware waves**. Plans within a wave run in parallel; waves run sequentially. Each plan executes in a **fresh subagent context** (200k tokens, zero accumulated garbage). Each task gets an atomic git commit.

```
WAVE 1 (parallel)          WAVE 2 (parallel)          WAVE 3
┌─────────┐ ┌─────────┐    ┌─────────┐ ┌─────────┐    ┌─────────┐
│ Plan 01 │ │ Plan 02 │ →  │ Plan 03 │ │ Plan 04 │ →  │ Plan 05 │
│ User    │ │ Product │    │ Orders  │ │ Cart    │    │ Checkout│
│ Model   │ │ Model   │    │ API     │ │ API     │    │ UI      │
└─────────┘ └─────────┘    └─────────┘ └─────────┘    └─────────┘
```

Vertical slices (complete feature per plan) over horizontal layers (all models, then all APIs).

### Phase 5: Verify (`/gsd:verify-work N`)

User acceptance testing: extracts testable deliverables → walks through each item → diagnoses failures with debug agents → creates fix plans for re-execution.

### Loop Structure

```
new-project → [discuss → plan → execute → verify] × N phases
                                                      ↓
                                              complete-milestone
                                                      ↓
                                               new-milestone
```

---

## Key Design Patterns

### 1. Context Isolation via Subagent Spawning

The central insight. The orchestrator stays lightweight (~30-40% context usage), delegating heavy lifting to subagents that each get a full fresh context window. This prevents the quality degradation that occurs when a single context accumulates tool results, code snippets, and conversation history.

**Trade-off:** Each subagent loses the accumulated context of previous work. GSD compensates by injecting curated state files (PROJECT.md, REQUIREMENTS.md, relevant PLAN.md) rather than raw history.

### 2. Orchestrator/Worker Split

```
Orchestrator (thin)          Workers (heavy)
├── Coordinates phases       ├── Researchers (4 parallel)
├── Manages state files      ├── Planner + Checker (iterative)
├── Groups into waves        ├── Executors (parallel per wave)
├── Tracks progress          └── Verifiers + Debuggers
└── Stays at ~30-40% context     └── Each gets fresh 200k context
```

### 3. Structured Task Format (XML)

Plans use XML with explicit verification criteria. This gives the executor precise scope and testable completion conditions, reducing ambiguity compared to natural language instructions.

### 4. Wave-Based Dependency Execution

Dependency graph → topological sort → group into waves → parallel within wave, sequential across waves. This is a standard pattern (make -j, task runners) applied to LLM subagent orchestration.

### 5. File-Based State as Context Anchor

Rather than relying on message history or database queries, GSD uses markdown files as the canonical state representation. These are simultaneously human-readable, LLM-readable, and version-controlled. Size limits prevent any single file from consuming too much context.

---

## Configuration

### Model Profiles

| Profile | Planning | Execution | Verification |
|---------|----------|-----------|--------------|
| `quality` | Opus | Opus | Sonnet |
| `balanced` | Opus | Sonnet | Sonnet |
| `budget` | Sonnet | Sonnet | Haiku |

### Workflow Toggles

| Setting | Default | Purpose |
|---------|---------|---------|
| `workflow.research` | `true` | Research domain before planning |
| `workflow.plan_check` | `true` | Verify plans against goals |
| `workflow.verifier` | `true` | Confirm deliverables after execution |
| `workflow.auto_advance` | `false` | Auto-chain discuss → plan → execute |

### Execution Settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `mode` | `interactive` | `yolo` auto-approves vs `interactive` confirms |
| `granularity` | `standard` | `coarse` / `standard` / `fine` phase slicing |
| `parallelization.enabled` | `true` | Parallel plan execution within waves |
| `git.branching_strategy` | `none` | `none` / `phase` / `milestone` branching |

---

## Strengths

1. **Context isolation solves a real problem.** Fresh subagent contexts per plan prevent the measurable quality degradation that occurs in long sessions. This is the most important insight in the system.

2. **Well-structured state management.** The file-based state system with size limits gives the LLM consistent anchoring without overwhelming the context window.

3. **Orchestrator/worker separation.** Keeping the orchestrator lightweight (~30-40% context) while workers get full contexts is architecturally sound.

4. **Explicit verification criteria.** XML task format with `<verify>` and `<done>` tags makes completion conditions unambiguous.

5. **Multi-runtime support.** Not locked to a single LLM vendor (Claude, OpenAI, Gemini, Codex).

6. **Atomic git commits.** Enables `git bisect`, clean reverts, and task-level observability.

7. **Quick mode escape hatch.** Not everything needs full ceremony — `/gsd:quick` for ad-hoc tasks.

## Weaknesses

1. **Prompt fragility.** The entire system is prompt-dependent with no programmatic validation layer. Model updates or different model interpretations can silently degrade behavior.

2. **Security defaults.** Recommends `--dangerously-skip-permissions` as the primary usage mode.

3. **No testable core behavior.** The 428 tests cover the installer/CLI, not the prompts that constitute the actual product.

4. **Cost opacity.** Parallel subagents across multiple waves with no cost estimation or budget controls.

5. **Brownfield limitations.** Optimized for greenfield; `map-codebase` exists but the rigid phase structure may not fit large existing codebases well.

6. **Limited error recovery within execution.** If a subagent fails mid-plan, recovery is deferred to the verify phase rather than handled inline.

---

## Applicability to micro-x-agent-loop-python

### Highly Applicable — Adopt These Patterns

#### 1. Context Isolation for Complex Task Execution

**GSD pattern:** Fresh subagent context per atomic plan.
**This project:** `TurnEngine` handles single turns; `compaction.py` manages long sessions via summarization. GSD's insight suggests an additional strategy: for complex multi-step tasks, spawn fresh subagent contexts with curated state injection rather than relying solely on compaction.

**Implementation path:** The `TurnEngine` could support a "fresh context" execution mode where a subtask receives only the system prompt + curated state (extracted from session history) rather than full message history. This would complement the existing summarization compaction strategy.

#### 2. Decompose → Execute → Verify Loop

**GSD pattern:** Plan phase → execute phase → verify phase, with explicit completion criteria.
**This project:** The agent currently processes each user turn as an independent request. There is no built-in mechanism for the agent to autonomously break a complex request into subtasks, execute them with isolated contexts, and verify results.

**Implementation path:** GSD provides a proven reference design for multi-step task orchestration:
1. Agent detects that a request is complex (multi-file, multi-step, or ambiguous)
2. Decomposition step breaks it into atomic subtasks with verification criteria
3. Each subtask executes via `TurnEngine` with isolated context
4. Verification step confirms results against criteria

This is the most directly actionable takeaway — GSD validates the **decompose → isolate → execute → verify** pattern as a proven shape for autonomous multi-step task execution.

#### 3. Structured State Summaries as Context Anchors

**GSD pattern:** PROJECT.md / REQUIREMENTS.md / STATE.md injected into each subagent.
**This project:** SQLite-backed memory with session persistence and checkpoints.

**Implementation path:** Generate lightweight state summary documents from session history/checkpoints and inject them into system prompts for subagent tasks. This bridges the gap between the raw message history (too large) and no context (too little). The existing `system_prompt.py` is the natural place for this injection.

#### 4. Wave-Based Parallel Execution

**GSD pattern:** Dependency-aware parallel waves with topological ordering.
**This project:** Sequential turn execution only.

**Implementation path:** If multi-step task orchestration is implemented, the wave pattern provides the right concurrency model. The MCP tool dispatch infrastructure already supports concurrent operations — a task graph layer on top would enable wave-based execution.

### Partially Applicable — Adapt Selectively

#### 5. Agent Role Specialization via System Prompts

**GSD pattern:** 12 distinct agent types with role-specific prompts.
**This project:** Single `Agent` class with one system prompt.

**Adaptation:** Don't create 12 agent types. Instead, support **phase-specific system prompt variants** in `system_prompt.py` — a research prompt, a planning prompt, an execution prompt, a verification prompt. The `Agent` remains a single class; only the injected directives change based on the current phase.

#### 6. XML-Structured Task Definitions

**GSD pattern:** `<task><action><verify><done>` XML format for plans.
**This project:** No structured task format.

**Adaptation:** For multi-step subtasks, define a structured format (doesn't have to be XML — could be a Python dataclass) with fields for: action description, target files, verification criteria, and completion condition. This makes subtask execution deterministic and verifiable.

#### 7. Atomic Git Integration

**GSD pattern:** One git commit per completed task with structured commit messages.
**This project:** Checkpoint system tracks pre-mutation state but no git integration.

**Adaptation:** The checkpoint service could optionally create git commits at checkpoint boundaries, providing both the SQLite-based rewind capability and git-level observability.

### Not Applicable

#### 8. Slash Command / Installer System

GSD distributes prompts via file copy. This project is a standalone Python runtime — no need for this pattern.

#### 9. `.planning/` Filesystem Database

GSD uses filesystem as database. This project already has SQLite-backed persistence, which is strictly better for querying, pruning, and cross-session analysis.

#### 10. Multi-Runtime Installer

GSD needs this because it's prompt-only. This project has a proper provider abstraction layer.

---

## Comparison with This Project's Existing Patterns

| Concern | GSD Approach | This Project's Approach | Assessment |
|---------|-------------|------------------------|------------|
| **Context management** | Fresh subagent contexts + file-based state | Compaction (none/summarize) | GSD's isolation is complementary; both strategies have value |
| **Task decomposition** | Manual phases + planner agent | Single-turn execution | GSD validates the decompose→execute→verify shape for multi-step orchestration |
| **State persistence** | Markdown files in `.planning/` | SQLite (sessions, messages, checkpoints) | This project's approach is more robust |
| **Multi-agent** | 12 agent prompt types | Single Agent class | Role specialization via prompt variants is the right adaptation |
| **Tool system** | N/A (relies on host agent's tools) | MCP tool proxying + pseudo-tools | This project is more capable |
| **Provider abstraction** | N/A (relies on host agent) | Anthropic + OpenAI providers | This project has proper abstraction |
| **Configuration** | JSON in `.planning/config.json` | `config.json` with base inheritance + env expansion | This project's config system is more sophisticated |
| **Error recovery** | Deferred to verify phase | Per-turn in TurnEngine | GSD's deferred approach is weaker |

---

## Key Insight for This Project

GSD's most important contribution to this project is **validating the decompose → isolate → execute → verify pattern** for autonomous multi-step task execution:

```
Agent (detect complexity) → Decomposer (plan) → Executor (isolated turns) → Verifier (check)
                                ↑ new                ↑ TurnEngine              ↑ new
                                                       (fresh context)
```

This pattern is proven in production (GSD claims adoption at Amazon, Google, Shopify, Webflow). The key architectural decision is implementing this as **runtime code with programmatic guarantees** rather than prompt-only orchestration — which is exactly the differentiation this project provides.

---

## Evaluation: GSD as a Development Tool for This Codebase

A separate question from pattern adoption: **should GSD be used to develop this project?**

### Project Profile

- 48 Python source files, ~7,080 lines of code
- 44 test files
- ~10 MCP servers (TypeScript, separate packages)
- Solo/small-team development, prefix-style commits
- Brownfield — mature architecture with 17 ADRs and extensive documentation

### Verdict: Poor fit. Not recommended.

#### 1. Brownfield codebase vs greenfield tool

GSD's strength is the init → discuss → plan → execute → verify pipeline starting from zero. This project has 48 modules, established patterns, 17 ADRs, and a defined architecture. GSD's `map-codebase` exists but is acknowledged as thin — the rigid phase structure doesn't adapt well to adding features to an existing system with established constraints and conventions.

#### 2. Codebase fits in context — context rot is not a problem

At ~7K lines across 48 files, the entire Python source fits comfortably within a single context window. GSD's core value — fighting context rot on large multi-file projects — doesn't apply. An AI agent can read every relevant file without needing context isolation.

#### 3. Ceremony exceeds project complexity

GSD's full workflow (PROJECT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md, CONTEXT.md, per-phase research, XML plans, wave execution, UAT verification) is designed for projects that take days or weeks of AI-assisted development. Typical work on this project — adding a feature, fixing a bug, refactoring a module — is a single-session task. The planning pipeline overhead would slow development, not accelerate it.

#### 4. Direct agent access is already effective

GSD is a layer on top of Claude Code (or similar agents). This project is already developed with direct AI agent access and a thorough CLAUDE.md that provides all necessary context. Adding GSD would insert a prompt-based orchestration layer with no clear benefit at this scale.

#### 5. Quick mode is the only realistic fit — but redundant

GSD's `/gsd:quick` for ad-hoc tasks is the only mode that matches this project's development cadence. But at that point it's just a structured prompt template — achievable with a CLAUDE.md instruction or a simple slash command.

#### 6. Philosophical mismatch

This project is built on runtime code with programmatic guarantees. Using a prompt-only framework to develop it would mean relying on prompt fragility to build a system designed to be more reliable than prompts.

### Where GSD would make sense for this project

- A new project with 50+ files planned across multiple phases
- A project where context rot is actually occurring (quality loss mid-session)
- Multi-day feature development where session continuity matters
- Teams coordinating multi-person AI-assisted development

---

## Project Type Applicability

GSD is not a general-purpose development framework. Its design choices constrain it to a specific project profile.

### Ideal GSD Projects

| Trait | Why |
|-------|-----|
| **Greenfield** | The entire pipeline assumes building from scratch — init → requirements → roadmap → phases |
| **Full-stack web apps / APIs** | Every example in the docs is web-oriented (login endpoints, user models, cart APIs, checkout UIs). Vertical-slice decomposition fits this well |
| **Well-defined scope** | "If you know clearly what you want, this WILL build it for you" — the system needs clear requirements to decompose into plans |
| **Medium-large builds** (days to weeks) | The ceremony pays off when there are 5+ phases with multiple plans per phase. Below that, it's overhead |
| **Solo developer or tiny team** | Designed for "people who want to describe what they need and have it built" — not for coordinating large engineering teams |
| **Context-exceeding codebases** | Context isolation only matters when generated code exceeds what fits in a single 200k token window |

### Poor Fit Projects

| Trait | Why |
|-------|-----|
| **Brownfield / maintenance** | Rigid phase structure doesn't map to "fix this bug" or "add a feature to existing module X" |
| **Libraries / frameworks / SDKs** | No clear "phases" — library development is iterative refinement, not feature buildout |
| **Data science / ML** | Experimental, exploratory work where requirements emerge through iteration |
| **Infrastructure / DevOps** | Config-heavy work doesn't benefit from plan → execute decomposition |
| **Small tasks** | Anything under ~500 lines of new code — the ceremony costs more than the work |
| **Highly iterative / discovery-driven** | GSD assumes requirements can be defined upfront. If the build is how you discover what to build, the workflow fights you |
| **Performance / optimization work** | Profile → hypothesize → measure cycles don't fit the linear phase model |

### The Core Constraint

GSD is fundamentally a **waterfall-shaped tool with parallel execution**. It works when three conditions are all met:

1. **Requirements are definable upfront** — you can describe what you want before building
2. **Work decomposes into independent vertical slices** — features can be built in parallel without constant cross-cutting concerns
3. **The build is large enough that context rot is a real problem** — the generated code exceeds a single context window

If any of those three conditions isn't met, GSD adds friction without value.

---

## Related Research

- [Compaction deep research](deep-research-compaction.md) — context window management strategies (GSD's isolation is an alternative to compaction)
- [Claude Code subagent architecture](claude-code-subagent-architecture.md) — subagent spawning patterns (GSD builds on Claude Code's subagent capability)
- [OpenAI Agents SDK multi-agent research](openai-agents-sdk-multi-agent-deep-research.md) — handoff patterns (GSD's orchestrator→executor is a form of handoff)
- [Key insights and takeaways](key-insights-and-takeaways.md) — cross-framework synthesis
