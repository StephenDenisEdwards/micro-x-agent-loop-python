# Get Shit Done (GSD) — Framework Review

**Date:** 2026-03-06
**Repository:** https://github.com/gsd-build/get-shit-done/
**Status:** Research complete
**Relevance:** Compiled mode execution, phase-based task decomposition, context management

---

## Executive Summary

GSD is a meta-prompting and context engineering framework for AI coding assistants (Claude Code, OpenCode, Gemini CLI, Codex). It solves "context rot" — the quality degradation that occurs as an AI fills its context window during long sessions. Instead of one long conversation, GSD breaks work into phases, gives each phase its own fresh AI session with a focused prompt, and orchestrates the results.

**Key stats:** ~5,400 lines of JavaScript, 535 tests, zero external npm dependencies, 12 specialised agents, 31 user commands.

---

## Purpose

AI coding assistants get worse the longer you use them in a single session. As the context window fills, the AI forgets earlier instructions, makes inconsistent decisions, and produces lower quality code.

GSD's solution: don't use one long session. Break work into phases, give each phase its own fresh 200k-token context, and orchestrate the results through specialised agents.

---

## How It's Used

### Workflow

```
User describes what they want
    ↓
/gsd:new-project → PROJECT.md, REQUIREMENTS.md, ROADMAP.md
    ↓
/gsd:plan-phase → Researcher → Planner → Checker → PLAN.md
    ↓
/gsd:execute-phase → Executor → Verifier → Code + Tests + Git commits
    ↓
/gsd:verify-work → Confirms deliverables against requirements
    ↓
Next phase (fresh context, no rot)
```

1. **Install:** `npx get-shit-done-cc@latest` — adds GSD commands to the AI session
2. **New project:** `/gsd:new-project` creates `.planning/` with project vision, requirements, and phased roadmap
3. **Plan a phase:** `/gsd:plan-phase --phase 01` spawns researcher → planner → checker agents, each with a fresh context window
4. **Execute:** `/gsd:execute-phase --phase 01` — executor writes code, runs tests, makes atomic git commits; verifier checks deliverables
5. **Repeat:** Each phase starts clean, no context rot
6. **Quick mode:** `/gsd:quick "add dark mode"` for smaller tasks without full project ceremony

---

## Architecture

### Agent System

12 specialised agents orchestrated by command workflows:

| Agent | Purpose | Model Profiles |
|-------|---------|---------------|
| **gsd-planner** | Task decomposition, dependency graphs, TDD specs | Opus / Sonnet |
| **gsd-executor** | Implements tasks, commits atomically, runs verification | Opus / Sonnet |
| **gsd-phase-researcher** | Investigates stack, features, architecture, pitfalls | Opus / Sonnet / Haiku |
| **gsd-project-researcher** | Domain research, competitive analysis | Opus / Sonnet / Haiku |
| **gsd-research-synthesizer** | Combines research into actionable insights | Sonnet |
| **gsd-plan-checker** | Validates plans against requirements (up to 3 iterations) | Sonnet |
| **gsd-verifier** | Confirms deliverables, identifies failures | Sonnet / Haiku |
| **gsd-debugger** | Root cause analysis, test-driven fixes | Opus / Sonnet |
| **gsd-roadmapper** | Phase breakdown with dependencies and effort estimates | Opus / Sonnet |
| **gsd-codebase-mapper** | Analyses existing codebase for brownfield projects | Sonnet / Haiku |
| **gsd-nyquist-auditor** | Maps test coverage to requirements before implementation | Sonnet |
| **gsd-integration-checker** | Validates integration between phase outputs | Sonnet |

**Coordination pattern:**
- Orchestrators spawn agents in parallel where possible
- Results flow sequentially when dependent: research → planner → checker → executor
- Each agent gets a fresh context window (prevents degradation)
- Model selection is user-configurable via profiles (quality / balanced / budget)

### State Management

All state lives in `.planning/` as human-readable markdown:

```
.planning/
├── config.json              # Model profile, workflow toggles
├── ROADMAP.md               # Phase sequencing, requirements traceability
├── PROJECT.md               # Vision, scope, architecture decisions
├── REQUIREMENTS.md          # Numbered requirements with IDs
├── STATE.md                 # Current position, blockers, decisions
├── phases/
│   ├── 01-foundation/
│   │   ├── PLAN.md          # Task breakdown (2-3 tasks per plan)
│   │   ├── SUMMARY.md       # Execution results
│   │   └── CONTEXT.md       # Phase-specific decisions
│   └── 02-features/
├── quick/                   # Ad-hoc task tracking
├── todos/                   # Captured ideas
└── research/                # Domain investigation
```

**Key design principle:** Every document is a prompt, not a document that becomes a prompt. When an agent reads `PLAN.md`, it executes the plan directly. The planning files ARE the instructions. This means state is simultaneously human-readable, machine-executable, and version-controllable.

### Core Modules

| Module | LOC | Purpose |
|--------|-----|---------|
| `gsd-tools.cjs` | 400+ | CLI dispatcher, command routing |
| `commands.cjs` | 700+ | 30+ utility commands (slug generation, todo management, history digest) |
| `phase.cjs` | 600+ | Phase CRUD, lifecycle, decimal phase calculation |
| `state.cjs` | 600+ | STATE.md operations, field extraction, blocker/decision tracking |
| `roadmap.cjs` | 450+ | ROADMAP.md parsing, phase sequencing, requirement tracking |
| `frontmatter.cjs` | 450+ | YAML frontmatter parsing, schema validation |
| `init.cjs` | 450+ | Workflow initialisation (plan-phase, execute-phase, verify-work) |
| `verify.cjs` | 600+ | Health checks, artifact verification, link validation |
| `template.cjs` | 250+ | Template loading, substitution |
| `config.cjs` | 300+ | Config creation, model profile detection |
| `milestone.cjs` | 350+ | Milestone completion, archiving |
| `core.cjs` | 350+ | Path utilities, git operations, config loading |

---

## Technical Assessment

### Strengths

| Area | Rating | Notes |
|------|--------|-------|
| **Dependencies** | A+ | Zero external production deps — only Node.js built-ins. Eliminates supply chain risk entirely. |
| **Architecture** | A | Multi-agent orchestration with context isolation, wave-based parallel execution, atomic git commits. |
| **Testing** | A | 535 passing tests, 70%+ coverage enforced, CI on 3 OS x 3 Node versions. Regression tests for known bugs. |
| **UX** | A | Single command install, 4 runtime support, model profiles (quality/balanced/budget). |
| **Documentation** | B+ | Excellent user docs (26KB README, detailed USER-GUIDE), but no ADRs and sparse code comments. |
| **Security** | B | No deps is great, but command injection vectors (`execSync` with string concatenation) and path traversal risk. |
| **Error handling** | B- | Fail-fast is good, but `safeReadFile()` silently returns null and workflows don't suggest recovery steps. |

**Overall grade: A-**

### Key Concerns

1. **Command injection** — Uses `execSync('git ' + args.join(' '))` string form instead of `execFileSync('git', args)` array form. Crafted phase names could inject shell commands.

2. **Path traversal** — Phase operations don't validate that paths stay within `.planning/`. A phase name like `../../etc` could escape.

3. **Large monolithic files** — `commands.cjs` (700+ LOC), `verify.cjs` (600+ LOC), `phase.cjs` (600+ LOC) should be split.

4. **No integration/E2E tests** — All 535 tests are unit tests. No test for a full new-project → plan → execute flow.

5. **No type safety** — Plain JavaScript with no JSDoc validation or TypeScript.

6. **Regex DoS potential** — Complex regex patterns for ROADMAP.md parsing could be slow on pathological input.

---

## Ideas Applicable to micro-x-agent-loop

Several patterns from GSD are directly relevant to compiled mode execution:

### Phase Decomposition

Breaking large tasks into numbered phases with dependency graphs. GSD limits plans to 2-3 tasks per phase — small enough to execute reliably, large enough to be meaningful. Each phase has clear inputs and outputs.

### Agent-Per-Phase with Context Isolation

Fresh context window per agent prevents quality degradation. This is the core insight — rather than cramming everything into one long conversation, give each sub-task a clean slate. The orchestrator passes only the relevant context forward.

### State-as-Markdown

Human-readable, git-trackable planning state. Files serve dual purpose: documentation for humans and executable prompts for agents. No database, no opaque state — everything is inspectable.

### Wave-Based Execution

Parallelise independent phases, sequence dependent ones. GSD analyses the dependency graph and runs independent work concurrently, then gates on results before starting the next wave.

### Model Profiles

Quality/balanced/budget profiles let users trade cost for quality. Different agents use different model tiers — researchers can use cheaper models while planners and executors use more capable ones.

### Nyquist Validation

Map test coverage to requirements before implementation. An auditor agent checks that the test plan covers all requirements, similar to Nyquist sampling — you need at least 2x the "signal frequency" in test coverage to faithfully reproduce the requirement.

### Atomic Git Commits

Each task gets its own commit with semantic naming. This enables bisect and rollback at the task level, not just the session level.

---

## Sources

- [Repository](https://github.com/gsd-build/get-shit-done/)
- [README](https://github.com/gsd-build/get-shit-done/blob/main/README.md)
- [USER-GUIDE](https://github.com/gsd-build/get-shit-done/blob/main/USER-GUIDE.md)
- [npm package](https://www.npmjs.com/package/get-shit-done-cc)
