# Claude Code Sub-Agent Architecture -- Deep Research

**Date:** 2026-02-26
**Status:** Complete
**Subject:** How Claude Code spawns and manages sub-agents via the Task tool -- model selection, tool isolation, system prompts, context boundaries

---

## 1. Overview

When Claude Code uses the **Task tool** to delegate work, it does **not** clone the parent agent. Instead it launches a **specialized sub-agent** -- a new, isolated agent instance with its own model, system prompt, tool set, and context window. Only a summary of the sub-agent's work flows back to the parent.

This design serves two goals:

1. **Context isolation** -- verbose intermediate output (file reads, search results, build logs) stays in the sub-agent's context and does not bloat the parent conversation.
2. **Specialization** -- each agent type can use a cheaper/faster model and a restricted tool set appropriate to its role.

---

## 2. Built-in Sub-Agent Types

Claude Code ships with several built-in agent types, each tailored for a specific class of task:

| Agent Type | Model | Tool Access | Purpose |
|---|---|---|---|
| **Explore** | Haiku | Read-only (Glob, Grep, Read, Bash, WebFetch, WebSearch) -- **no** Edit, Write, NotebookEdit, Task | Fast codebase exploration: find files, search code, answer structural questions |
| **Plan** | Inherits from parent | Read-only (same exclusions as Explore) | Codebase research during plan mode; designs implementation approaches |
| **general-purpose** | Inherits from parent | All tools (including Edit, Write, Task) | Complex multi-step tasks that need both exploration and modification |
| **claude-code-guide** | Haiku | Glob, Grep, Read, WebFetch, WebSearch | Answers questions about Claude Code features, hooks, settings, SDK |
| **statusline-setup** | Sonnet | Read, Edit | Configures the user's Claude Code status line |

### Model override

Any sub-agent invocation can specify `model: "sonnet" | "opus" | "haiku"`. If omitted, the sub-agent inherits the parent's model. The Explore and claude-code-guide agents default to Haiku for cost/speed regardless of the parent model.

---

## 3. How Sub-Agents Differ from the Parent

### 3.1 Separate context window

Each sub-agent starts with a **fresh context window**. It does not inherit the parent's conversation history. The parent passes a task description via the `prompt` parameter, and the sub-agent works autonomously from there.

When the sub-agent finishes, only its **summary result** is returned to the parent -- not the full transcript.

### 3.2 Different system prompts

Sub-agents receive their own system prompt, not the full parent system prompt. For built-in agents this is a focused prompt optimized for the agent's role (e.g. the Explore agent's prompt emphasizes fast file discovery and code search). For custom agents defined in `.claude/agents/*.md` files, the Markdown body becomes the system prompt.

### 3.3 Restricted tool sets

Tool access is controlled per agent type:

- **Read-only agents** (Explore, Plan) explicitly deny Edit, Write, NotebookEdit, and Task.
- **General-purpose** agents inherit all tools from the parent.
- **Custom agents** can specify an explicit tool allowlist via the `tools` frontmatter field or the `AgentDefinition.tools` parameter in the SDK.

### 3.4 No nesting

Sub-agents **cannot spawn their own sub-agents**. The Task tool is excluded from read-only agents and should not be included in custom agent tool lists. Delegation is strictly one level deep. If multi-level orchestration is needed, the parent chains sequential sub-agent calls.

### 3.5 Independent permissions

Sub-agents can override the parent's permission mode:

| Mode | Behavior |
|---|---|
| `default` | Standard permission checking with user prompts |
| `acceptEdits` | Auto-approve file edits |
| `dontAsk` | Auto-deny permission prompts (fail silently) |
| `bypassPermissions` | Skip all permission checks |
| `plan` | Read-only, no tool execution |

---

## 4. Architecture Diagram

```
Parent Agent (e.g. Opus, full tools, full conversation context)
│
├── Task(subagent_type="Explore")
│     Model:   Haiku (fixed)
│     Tools:   Read-only (Glob, Grep, Read, Bash, WebFetch, WebSearch)
│     Prompt:  Explore-specific system prompt
│     Context: Fresh window
│     Returns: Summary → parent
│
├── Task(subagent_type="Plan")
│     Model:   Inherited from parent
│     Tools:   Read-only (same as Explore)
│     Prompt:  Plan-specific system prompt
│     Context: Fresh window
│     Returns: Summary → parent
│
├── Task(subagent_type="general-purpose")
│     Model:   Inherited from parent
│     Tools:   All tools (Edit, Write, Bash, etc.)
│     Prompt:  General-purpose system prompt
│     Context: Fresh window
│     Returns: Summary → parent
│
└── Task(subagent_type="claude-code-guide")
      Model:   Haiku (fixed)
      Tools:   Glob, Grep, Read, WebFetch, WebSearch
      Prompt:  Claude Code documentation prompt
      Context: Fresh window
      Returns: Summary → parent
```

---

## 5. Custom Sub-Agents

Beyond the built-in types, users can define custom sub-agents in two ways:

### 5.1 Filesystem-based (`.claude/agents/*.md`)

```markdown
---
name: code-reviewer
description: Expert code reviewer. Use proactively after code changes.
tools: [Read, Glob, Grep]
model: sonnet
permissionMode: plan
---

You are a senior code reviewer focusing on code quality, security,
and best practices. Provide actionable feedback without modifying code.
```

The frontmatter controls model, tools, and permissions. The Markdown body becomes the system prompt. Claude automatically delegates to this agent when a task matches the `description`.

### 5.2 Programmatic (Claude Agent SDK)

```python
from claude_agent_sdk import ClaudeAgentOptions, AgentDefinition

options = ClaudeAgentOptions(
    allowed_tools=["Read", "Grep", "Glob", "Task"],
    agents={
        "code-reviewer": AgentDefinition(
            description="Expert code reviewer for quality and security reviews.",
            prompt="You are a code review specialist...",
            tools=["Read", "Grep", "Glob"],
            model="sonnet",
        ),
    },
)
```

---

## 6. Execution Modes

### Foreground (default)

The parent blocks until the sub-agent completes and returns its result. Use when the parent needs the sub-agent's output before proceeding.

### Background

The parent continues working while the sub-agent runs. The parent is notified when the sub-agent completes. Use for independent, parallelizable work.

### Worktree isolation

Sub-agents can optionally run in a temporary git worktree (`isolation: "worktree"`), giving them an isolated copy of the repository. The worktree is automatically cleaned up if no changes are made; otherwise the worktree path and branch are returned.

### Resumable

Sub-agents return an `agentId` that can be passed back via the `resume` parameter to continue a previous sub-agent's work with its full context preserved.

---

## 7. Comparison: Claude Code vs. OpenClaw Sub-Agents

| Dimension | Claude Code | OpenClaw |
|---|---|---|
| **Spawn mechanism** | `Task` built-in tool | `sessions_spawn` tool |
| **Blocking** | Foreground (blocking) or background | Non-blocking (always async) |
| **Nesting depth** | 1 (no nesting) | Configurable 1-5 (default 1) |
| **Concurrency** | Multiple sub-agents in parallel | `maxConcurrent` (default 8) + per-session cap (default 5) |
| **Context injection** | Fresh window, prompt only | Injects `AGENTS.md` + `TOOLS.md` (subset of full context) |
| **Result delivery** | Summary returned to parent via tool result | Announce step posts summary to requester channel |
| **Model override** | Per-agent (`sonnet`, `opus`, `haiku`, `inherit`) | Per-spawn or via `agents.defaults.subagents.model` |
| **Auto-cleanup** | Worktree auto-cleanup | Session archived after `archiveAfterMinutes` (default 60) |

---

## 8. Key Takeaways for micro-x Design

1. **Specialization pays off.** Using cheaper, faster models (Haiku) for read-only exploration tasks reduces cost and latency without sacrificing quality for the parent's reasoning.
2. **Context isolation is essential.** Sub-agent transcripts staying separate from the parent prevents context window exhaustion -- especially important for exploration-heavy workflows.
3. **One level of nesting is sufficient.** Claude Code's restriction to single-level delegation simplifies orchestration and avoids runaway agent chains. The parent can chain multiple sequential sub-agent calls for complex workflows.
4. **Tool restriction is a first-class concern.** Every sub-agent type has an explicit tool policy. Read-only agents cannot accidentally modify files; exploration agents cannot spawn further agents.
5. **Resume capability enables iterative workflows.** Sub-agents can be resumed with their full context preserved, enabling follow-up queries without re-doing prior work.

---

## Sources

- Claude Code built-in Task tool documentation (system prompt analysis)
- [Claude Agent SDK -- Subagents](https://platform.claude.com/docs/en/agent-sdk/subagents)
- [Claude Code Documentation](https://code.claude.com/docs)
- [How Claude Code Works](https://code.claude.com/docs/en/how-claude-code-works)
