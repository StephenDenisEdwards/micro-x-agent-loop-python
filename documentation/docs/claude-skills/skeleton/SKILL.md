---
name: skeleton
description: Template skill for creating new skills. Use this as a starting point when building custom slash commands.
disable-model-invocation: true
---

# Skeleton Skill

This is a template skill. Copy this directory to create a new skill:

```bash
cp -r .claude/skills/skeleton .claude/skills/my-new-skill
```

Then edit the `SKILL.md` frontmatter and instructions to match your use case.

## Frontmatter Reference

```yaml
---
name: my-skill              # Slash command name (lowercase, hyphens, max 64 chars)
description: When to invoke  # Claude uses this for auto-invocation
disable-model-invocation: true  # Set true for manual-only (/name) triggers
# allowed-tools: Read, Grep  # Optional: restrict available tools
# context: fork              # Optional: run in isolated subagent
# agent: Explore             # Optional: Explore, Plan, general-purpose
---
```

## Instructions Section

Write your skill instructions here. Claude follows these when the skill is invoked.

You can use `$ARGUMENTS` to capture text passed after the slash command (e.g., `/my-skill some args`).

You can inject live data with shell commands:
- `!`​`git status` — runs before Claude sees the prompt
- `!`​`gh pr view` — inject PR details dynamically

## Supporting Files

Add optional files alongside SKILL.md:
- `template.md` — templates for Claude to fill in
- `examples/` — example outputs
- `scripts/` — helper scripts Claude can execute
