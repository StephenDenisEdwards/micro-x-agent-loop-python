# Plan: Implement `ask_user` Pseudo-Tool

## Status

Completed

## Context

The agent loop was unidirectional — the user provides input, the agent processes it, and returns output. The LLM could not pause mid-execution to ask the user a clarifying question, present choices, or request approval. This led to wasted tokens on wrong interpretations and missed opportunities for user input on design decisions.

This plan implements the Claude Code `AskUserQuestion` pattern: a pseudo-tool the LLM can call that presents a structured question to the user, collects the answer, and returns it as a normal `tool_result`. The existing `tool_search` special-casing in `turn_engine.py` was the direct precedent.

See [research/human-in-the-loop-user-questioning.md](../research/human-in-the-loop-user-questioning.md) for background research.

## Design

The LLM calls an `ask_user` tool with a `question` string and optional `options` array (2-4 items with `label`/`description`). The handler prints the question to the terminal, collects the user's answer (numeric selection or free text), and returns `{"answer": "..."}` as a tool result. The LLM continues with the answer in context.

**Key design decisions:**
- Always-on (no config flag) — every agent benefits from being able to ask clarifying questions
- Pseudo-tool pattern: handled inline in `turn_engine.py`, same as `tool_search` — no spinner, no checkpoint, no event callbacks
- Terminal-based I/O via `asyncio.to_thread(input, ...)` to avoid blocking the event loop
- Numeric input maps to option labels; free text passed through as-is

## Files Created

### `src/micro_x_agent_loop/ask_user.py`

Contains:

- **`ASK_USER_SCHEMA`** — tool schema dict with name `"ask_user"`, required `question` string, optional `options` array (2-4 items, each with `label` and `description`)
- **`AskUserHandler`** class:
  - `__init__(self, *, line_prefix, user_prompt)` — stores display config
  - `is_ask_user_call(tool_name) -> bool` — static method, returns `tool_name == "ask_user"`
  - `get_schema() -> dict` — static method, returns `ASK_USER_SCHEMA`
  - `async handle(self, tool_input) -> str` — presents question, collects answer, returns `json.dumps({"answer": ...})`

**Implementation note:** The initial plan specified basic `input()` with numeric mapping. The actual implementation uses `questionary` for a richer interactive experience — arrow-key selection with styled options and an "Other (type your own)" escape hatch. Falls back to plain `input()` for non-interactive terminals (piped stdin). The `questionary>=2.0.0` dependency was added to `pyproject.toml`.

### `tests/test_ask_user.py`

15 tests covering:

**Unit tests for `AskUserHandler`:**
- `is_ask_user_call` — true for "ask_user", false for others
- `get_schema` — has correct name, required fields, properties
- `handle` with options + numeric input → returns matching option label
- `handle` with options + free text → returns the typed text
- `handle` without options → returns typed text
- `handle` with out-of-range number → returns raw text
- `handle` returns valid JSON with "answer" key

**TurnEngine integration tests** (following `test_tool_search.py` patterns — `RecordingEvents`, `FakeStreamProvider`):
- ask_user only → results appended, loop continues, no spinner/checkpoint
- ask_user mixed with regular tools → both handled, results merged in order
- no handler → "ask_user" treated as unknown tool error
- schema injection verified

## Files Modified

### `src/micro_x_agent_loop/system_prompt.py`

Added `_ASK_USER_DIRECTIVE` constant (following the `_TOOL_SEARCH_DIRECTIVE` pattern) with guidance on when to use the tool (ambiguous requests, multiple approaches, destructive actions, missing information) and when not to (routine confirmations, answerable from context, stalling).

### `src/micro_x_agent_loop/turn_engine.py`

- **Constructor** — added `ask_user_handler: AskUserHandler | None = None` parameter (optional, defaults to `None` for backward compatibility)
- **`api_tools` injection** — if handler is present, appends `ask_user_handler.get_schema()` to the tools list sent to the API
- **Block classification** — extended the two-way split (search/regular) to a three-way split (search/ask_user/regular) by checking `is_tool_search_call()` then `is_ask_user_call()` for each block
- **ask_user handling** — for each ask_user block, calls `await handler.handle(block["input"])` and builds a tool_result dict, added to `inline_results`
- **Pseudo-tool-only fast path** — changed condition from `search_blocks and not regular_blocks` to `not regular_blocks` with combined `inline_results` (search + ask_user)
- **Result merging** — passes combined `inline_results` to `_merge_tool_results()`
- **Renamed `_merge_tool_results` params** — `search_results` → `inline_results` for clarity since it now handles both search and ask_user results

### `src/micro_x_agent_loop/agent.py`

- Imported `AskUserHandler` and `_ASK_USER_DIRECTIVE`
- Created `self._ask_user_handler = AskUserHandler(line_prefix=self._LINE_PREFIX, user_prompt=self._USER_PROMPT)`
- Appended `_ASK_USER_DIRECTIVE` to `self._system_prompt`
- Passed `ask_user_handler=self._ask_user_handler` to `TurnEngine(...)` constructor

## Files NOT Changed

`bootstrap.py`, `agent_config.py`, `app_config.py`, `tool.py` — ask_user is always-on, no config flag needed. Agent wires everything internally (same as tool_search).

## Data Flow

```
LLM response includes tool_use "ask_user" with question + optional options
  |
  v
TurnEngine classifies block as ask_user (not search, not regular)
  |
  v
AskUserHandler.handle() prints question + options to terminal
  User types "2" or "Actually, use approach C"
  -> Maps numeric to option label, or passes free text
  -> Returns json: {"answer": "Option B"}
  |
  v
Result added to inline_results (alongside any tool_search results)
  |
  v
If no regular tools: append inline_results, continue loop
If regular tools: execute them, merge all results in original order
  |
  v
LLM receives tool_result with user's answer, continues execution
```

## Verification

1. `pytest tests/test_ask_user.py` — all 15 new tests pass
2. `pytest` — all existing tests still pass (new TurnEngine param is optional, defaults to None)
3. Manual test: start the agent, give an ambiguous task, verify the LLM calls `ask_user` with structured options, select an option by number, verify the LLM continues with the answer
4. Manual test: select "type your own answer" path by entering free text instead of a number
