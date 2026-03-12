# Code Review Index

This folder contains code review documents for micro-x-agent-loop-python. Each review assesses a specific concern area against the current codebase and roadmap, records findings, and tracks whether review items have been acted upon.

## Reviews

| Document | Topic | Date | Open Items |
|----------|-------|------|------------|
| [cost-reduction-review.md](cost-reduction-review.md) | Cost reduction strategies across all LLM API spend levers | 2026-03-12 | 6 high-priority items unaddressed (see summary table) |

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
