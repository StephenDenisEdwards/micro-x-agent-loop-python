# Issues

Tracked design issues and architectural problems that need a decision before
implementation, or that resolved a real bug after debate. Distinct from ADRs
(which record decisions already made) — issues are open questions or
problems-with-options.

## Template

```markdown
# ISSUE-XXX: Short title

## Date
YYYY-MM-DD

## Status
Open | Resolved | Near Complete | Reference

## Summary
What's wrong, in one or two paragraphs.

## Why this isn't a quick fix
The structural reason a one-line patch won't do.

## Options considered
### Option A — short label
Pros / Cons

### Option B — short label
Pros / Cons

## Recommendation
Which option, and why.

## Acceptance criteria
What must be true for this issue to be considered resolved.

## Related
Pointers to files, ADRs, other issues.
```

## Index

| Issue | Title | Date | Status |
|-------|-------|------|--------|
| [ISSUE-001](ISSUE-001-adr-014-flawed-premise.md) | ADR-014 is based on a flawed premise | — | Resolved |
| [ISSUE-002](ISSUE-002-ollama-tool-search-prompt-too-passive.md) | Small models select wrong tool due to noisy tool_search results | — | Resolved (2026-03-22) |
| [ISSUE-003](ISSUE-003-ollama-tool-calling.md) | Ollama tool calling — working-example session log | 2026-03-23 | Reference |
| [ISSUE-004](ISSUE-004-solid-dry-kiss-compliance-2026-04-01.md) | SOLID, DRY, and KISS compliance gaps | 2026-04-01 | Near Complete |
| [ISSUE-005](ISSUE-005-bash-tool-bypasses-path-policy.md) | `bash` tool bypasses filesystem path policy | 2026-05-06 | Open |
| [ISSUE-006](ISSUE-006-playwright-profile-contention.md) | Playwright profile contention between agent and codegen tasks | 2026-05-08 | Open |

## Conventions

- Filenames are `ISSUE-XXX-short-slug.md`. Some early entries embed the date in the slug (e.g. ISSUE-004); newer entries put the date inside the document instead.
- Statuses:
  - **Open** — design decision not yet made.
  - **Near Complete** — most actions done; tracking the long tail.
  - **Resolved** — fixed; the document remains as a record.
  - **Reference** — the document captures observations or a working example, not a problem to fix.
- When an issue is resolved, update its `## Status` line and add a `## Resolution` section in the document; also bump its row in this index.
- Add new issues to the table in numeric order. Don't reuse numbers.
