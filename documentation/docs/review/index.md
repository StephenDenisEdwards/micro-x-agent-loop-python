# Code Review Index

This folder contains code review documents for micro-x-agent-loop-python. Each review assesses a specific concern area against the current codebase and roadmap, records findings, and tracks whether review items have been acted upon.

## Reviews

| Document | Topic | Date | Open Items |
|----------|-------|------|------------|
| [cost-reduction-review.md](cost-reduction-review.md) | Cost reduction strategies across all LLM API spend levers | 2026-03-12 | 6 high-priority items unaddressed (see summary table) |
| [tool-result-summarisation-investigation.md](tool-result-summarisation-investigation.md) | Deep investigation — tool result summarisation with structured results | 2026-03-12 | Phase 1 formatter extensions not yet built |
| [claude-code-feature-comparison.md](claude-code-feature-comparison.md) | Feature-by-feature comparison against Claude Code agent infrastructure | 2026-04-06 | 3 priority gaps: lifecycle hooks, permissions, typed memory |
| [prompt-versioning-review.md](prompt-versioning-review.md) | Prompt versioning — current content-addressed storage vs. patterns in other agents | 2026-06-05 | 2 recommended cheap additions (`PROMPT_SCHEMA_VERSION` constant, `/replay --diff`); full registry deferred until evals exist |
| [codebase-review-2026-06-05.md](codebase-review-2026-06-05.md) | Full-codebase audit — architecture, coding standards, type hygiene, test coverage & quality, structure | 2026-06-05 | 30 open items across 4 tiers: T1 (9 must-fix incl. 5 failing tests, 2 mypy errors, ADR-024 dist violation), T2 (8 architecture), T3 (7 test quality), T4 (6 hygiene) |

### Manual Test Plans

| Document | Strategy | Scope |
|----------|----------|-------|
| [MANUAL-TEST-prompt-caching.md](../testing/MANUAL-TEST-prompt-caching.md) | Strategy 1 — Prompt Caching | 5 tests: cache headers, cache reads, disabled config, no-tools edge case, cost savings |
| [MANUAL-TEST-compaction-model.md](../testing/MANUAL-TEST-compaction-model.md) | Strategy 2 — Cheap Model for Compaction | 4 tests: cheap model used, fallback to main model, metrics, summary quality |
| [MANUAL-TEST-compaction-strategy.md](../testing/MANUAL-TEST-compaction-strategy.md) | Strategy 3 — Conversation History Summarisation | 8 tests: threshold trigger, below threshold, smart trigger, boundary pairs, context preservation, error fallback, none strategy, role alternation |

## How to Use This Index

- **Open items** — items in a review where `Action taken` is blank and status is not `✅ Done`.
- When an item is acted upon, update the `Action taken` field in the review document with a brief note (e.g., `Implemented in commit abc123`, `Superseded by PLAN-xyz.md`, `Won't fix — see rationale`).
- Update the `Open Items` count in this index to reflect current state.
- Add new review documents to the table above as they are created.
