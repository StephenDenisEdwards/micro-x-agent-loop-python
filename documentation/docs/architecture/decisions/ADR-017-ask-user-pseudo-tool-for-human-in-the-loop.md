# ADR-017: Ask User Pseudo-Tool for Human-in-the-Loop Questioning

## Status

Accepted

## Context

The agent loop was unidirectional — the user provides input, the agent processes it, and returns output. The LLM could not pause mid-execution to ask the user a clarifying question, present choices, or request approval. This led to wasted tokens on wrong interpretations and missed opportunities for user input on design decisions.

Research surveyed 8 agent systems (Claude Code, Cline, LangGraph, OpenAI Agents SDK, Mastra, Aider, OpenClaw, and others) and identified 6 architectural patterns for human-in-the-loop questioning. See [human-in-the-loop-user-questioning.md](../../research/human-in-the-loop-user-questioning.md).

### Patterns considered

| Pattern | Description | Rejected because |
|---------|-------------|------------------|
| 1. Tool-as-Question | LLM calls a pseudo-tool; handler prompts user, returns answer as tool_result | **Selected** |
| 2. Interrupt callback | Framework fires an interrupt event; orchestrator pauses | Requires framework-level interrupt semantics we don't have |
| 3. Structured output classification | LLM returns a typed "question" output; orchestrator detects and routes | Requires structured output mode, breaks streaming |
| 4. Dedicated question turn type | New message role (e.g. `question`) alongside `assistant`/`user` | Non-standard, breaks API contract |
| 5. Breakpoint/checkpoint | Orchestrator sets breakpoints; LLM hits them and pauses | Over-engineered for simple Q&A |
| 6. Approval gate | Hard-coded gates before dangerous actions | Too rigid, doesn't handle open-ended questions |

### Why always-on (no config flag)

Every agent benefits from being able to ask clarifying questions. Making it opt-in would mean most users never discover it. The cost is one extra tool schema (~200 tokens) — negligible. The `tool_search` pseudo-tool established the precedent for always-injected pseudo-tools.

## Decision

Implement Pattern 1 (Tool-as-Question) as a pseudo-tool named `ask_user`, following the same inline-handling pattern as `tool_search` in `turn_engine.py`.

- **Schema**: `question` (required string) + `options` (optional array of 2-4 items with `label`/`description`)
- **Handling**: three-way block classification in `turn_engine.py` (search / ask_user / regular). Ask-user blocks are handled inline before regular tool execution — no spinner, no checkpoint, no event callbacks.
- **UI**: `questionary` library provides arrow-key selection with an "Other (type your own)" escape hatch. Falls back to plain `input()` for non-interactive terminals.
- **Return format**: `{"answer": "..."}` as a tool_result string
- **System prompt directive**: guidance on when to use (ambiguous, multiple approaches, destructive, missing info) and when not to (routine confirmations, answerable from context)

## Consequences

### Positive

- The LLM can ask clarifying questions before committing to an approach, reducing wasted tokens and wrong interpretations
- Users get structured choices with arrow-key selection, improving the interaction quality over free-text-only input
- No configuration needed — works out of the box for all users
- Follows the established pseudo-tool pattern (`tool_search`), keeping the architecture consistent
- The "Other" option preserves full user agency — structured options don't constrain the user

### Negative

- Adds `questionary` as a runtime dependency
- The LLM may occasionally over-use the tool for questions it could answer from context (mitigated by system prompt guidance)
- Non-interactive terminals (piped stdin) fall back to plain text input without arrow-key selection
