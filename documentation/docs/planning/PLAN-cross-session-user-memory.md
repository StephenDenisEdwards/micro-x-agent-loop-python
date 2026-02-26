# Plan: Cross-Session User Memory

## Status

Planned

## Problem

All memory in the agent is session-scoped. When a user starts a new session, all learned context (preferences, project structure, workflow conventions, prior decisions) is lost. The user must re-explain the same things every session.

Claude Code solves this with "auto memory" — markdown files that persist across sessions, loaded into every conversation. This plan adds the same capability.

## Design Principles

- **File-based, human-editable** — Markdown files in `.micro_x/memory/`, not opaque DB rows. Users can read, edit, and version-control their memory files.
- **Agent-writable** — The LLM can save learnings via a dedicated tool, not just the user via commands.
- **Loaded every session** — Memory content is injected into context at session start so the LLM always has it.
- **Bounded** — A line cap on the main file prevents unbounded context bloat.
- **Opt-in** — Controlled by a config flag; disabled by default.

## Architecture

### Storage

```
.micro_x/memory/
  MEMORY.md          ← main file, first 200 lines loaded every session
  patterns.md        ← topic file (optional, loaded on demand)
  debugging.md       ← topic file (optional, loaded on demand)
  ...
```

- **Location**: `.micro_x/memory/` in the project working directory (alongside `memory.db`).
- **Main file**: `MEMORY.md` — first 200 lines injected into context at session start. The LLM maintains this as an index with links to topic files.
- **Topic files**: Additional `.md` files for detailed notes. Referenced from MEMORY.md. Loaded on demand when the LLM reads them.

Why files, not SQLite: human-readable, editable with any text editor, easy to version-control, matches Claude Code's proven approach.

### Context Injection

Inject memory content into the **system prompt** at bootstrap time. Extend `get_system_prompt()` to accept optional memory text and append it:

```python
def get_system_prompt(*, user_memory: str = "") -> str:
    base = f"""...(existing prompt)..."""
    if user_memory:
        base += f"\n\n# User Memory\n\n{user_memory}"
    return base
```

In `bootstrap.py`, before creating the Agent:
1. Check if `.micro_x/memory/MEMORY.md` exists
2. Read first 200 lines
3. Pass to `get_system_prompt(user_memory=content)`

On `/session new` and `/session resume`: the system prompt is static per process, so memory is loaded once at startup. This matches Claude Code's behavior (memory is loaded at conversation start, not re-read mid-conversation). The LLM's writes to memory files take effect in the *next* session.

### LLM Tool: `save_memory`

A dedicated tool the LLM uses to persist learnings. Constrained to `.micro_x/memory/` only.

```
Tool: save_memory
Parameters:
  - file: str       # filename within .micro_x/memory/ (e.g. "MEMORY.md", "patterns.md")
  - content: str    # full file content to write
Description: Save persistent memory that will be loaded in future sessions.
  Use MEMORY.md as the main index (first 200 lines loaded automatically).
  Create topic files for detailed notes and reference them from MEMORY.md.
```

Why a dedicated tool instead of reusing `write_file`:
- Sandboxed to the memory directory (can't accidentally write elsewhere)
- Clear semantic intent in the tool schema helps the LLM understand when to use it
- Doesn't trigger file checkpointing (memory writes are intentional, not rewindable)

### User Command: `/memory`

```
/memory              — display current MEMORY.md contents
/memory edit         — open MEMORY.md in $EDITOR (or print path if no editor)
/memory list         — list all files in .micro_x/memory/
/memory reset        — delete all memory files (with confirmation)
```

### When the LLM Should Save Memory

Include guidance in the system prompt (when memory is enabled):

```
You have persistent memory in .micro_x/memory/. As you work:
- Save stable patterns confirmed across interactions to MEMORY.md
- Save key architectural decisions, important file paths, project structure
- Save user preferences for workflow, tools, and communication style
- Save solutions to recurring problems
- Do NOT save session-specific context or in-progress work
- Do NOT save speculative conclusions from a single observation
- When the user explicitly asks you to remember something, save it immediately
```

## Config Additions

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `UserMemoryEnabled` | bool | `false` | Enable cross-session user memory |
| `UserMemoryDir` | string | `.micro_x/memory` | Directory for memory files |
| `UserMemoryMaxLines` | int | `200` | Max lines loaded from MEMORY.md into context |

## Implementation Plan

### Phase 1: Read Path (Low Risk)

1. Add config fields (`UserMemoryEnabled`, `UserMemoryDir`, `UserMemoryMaxLines`)
2. At bootstrap, read `MEMORY.md` (up to max lines) and inject into system prompt
3. Add `/memory` command (view, list)
4. Add memory guidance to system prompt when enabled

**Acceptance**: Start agent with an existing `MEMORY.md`, verify its content appears in the system prompt, verify `/memory` displays it.

### Phase 2: Write Path (Medium Risk)

1. Implement `save_memory` tool (write files within memory dir only)
2. Register tool when `UserMemoryEnabled=true`
3. Add `/memory edit` and `/memory reset` commands

**Acceptance**: Ask the LLM to remember a preference, verify it writes to MEMORY.md, start a new session, verify the preference is in context.

### Phase 3: Polish (Low Risk)

1. Add topic file support (LLM creates separate .md files, references from MEMORY.md)
2. Add line count warning when MEMORY.md exceeds max lines
3. Tests

**Acceptance**: LLM creates a topic file, references it from MEMORY.md, can read topic files on demand.

## Files Changed

| File | Change |
|------|--------|
| `agent_config.py` | Add `user_memory_enabled`, `user_memory_dir`, `user_memory_max_lines` fields |
| `app_config.py` | Add config parsing for new fields |
| `bootstrap.py` | Read MEMORY.md at startup, pass to `get_system_prompt()` |
| `system_prompt.py` | Accept optional `user_memory` parameter, append to prompt |
| **New:** `tools/save_memory_tool.py` | `save_memory` tool implementation |
| `tool_registry.py` | Register `save_memory` when enabled |
| `agent.py` | Add `/memory` command handler |
| `commands/router.py` | Register `/memory` route |

## Relationship to Existing Memory System

This is **complementary** to the session memory system (PLAN-claude-style-memory.md):

| Aspect | Session Memory (existing) | User Memory (this plan) |
|--------|--------------------------|------------------------|
| Scope | Per-session | Cross-session |
| Content | Conversation transcript, tool calls, checkpoints | User preferences, project knowledge, patterns |
| Storage | SQLite (`memory.db`) | Markdown files (`.micro_x/memory/`) |
| Written by | System (automatic) | LLM (via tool) + user (via editor) |
| Loaded | On session resume | On every session start |
| Purpose | "What happened" | "What to remember" |

## Risk Register

1. **Unbounded memory growth** — Mitigation: 200-line cap on auto-loaded content; LLM guidance to keep MEMORY.md concise
2. **Stale/wrong memories** — Mitigation: human-editable files; `/memory` command for review; LLM instructed to update/remove outdated entries
3. **Secret leakage** — Mitigation: memory files are local, `.micro_x/` can be gitignored, LLM instructed not to save secrets
4. **Context overhead** — Mitigation: 200 lines ≈ 500-1000 tokens, negligible vs typical 100K+ context windows
