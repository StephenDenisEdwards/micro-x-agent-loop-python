---
name: plan-update
description: Update planning index hygiene after completing feature work or committing changes. Syncs PLAN-*.md status with INDEX.md, updates counts, and moves completed items.
---

# Plan Update

After feature work or commits, synchronise planning docs to reflect reality.

## Steps

1. **Identify the plan**: If `$ARGUMENTS` names a plan (e.g., "cost-reduction", "sub-agents"), target `documentation/docs/planning/PLAN-$ARGUMENTS.md`. If no argument, check `!`​`git log --oneline -5` and infer which plan(s) were affected by recent work.

2. **Read the plan file**: Check its current `Status` field and phase statuses.

3. **Read INDEX.md**: Find the matching row(s) in `documentation/docs/planning/INDEX.md`.

4. **Sync status**: Update INDEX.md to match the plan file's actual status. Valid statuses: `Draft`, `Planned`, `In Progress`, `**Completed**`, `**Blocked**`, `**Dropped**`, `**Superseded**`.

5. **Move completed items**: If a plan has moved to Completed, remove it from the Priority Queue table and add it to the "Completed priorities" collapsible `<details>` section at the bottom, preserving alphabetical or chronological order.

6. **Update the Status Summary table**: Recount all plans by status and update the count table at the bottom of INDEX.md.

7. **Update the "Last updated" date** at the top of INDEX.md to today's date.

8. **Report what changed**: Summarise which files were modified and what status transitions occurred.

## Rules

- Never change the actual plan content — only status fields and INDEX.md bookkeeping.
- If a plan's status is ambiguous, ask the user rather than guessing.
- Preserve existing table formatting and column alignment.
- Do not reorder the Priority Queue — only modify status values and move completed rows.
