# Plan: Codegen Prompt Discipline & Infrastructure File Deny

**Status: Completed** (2026-03-02)

## Context

The codegen MCP server's inner LLM (Sonnet 4.6) wasted API turns reading infrastructure files it was told not to modify, then generated excessively verbose output that hit the max_tokens limit. A 700-line app shouldn't need 32K output tokens or multiple wasted turns. Root causes:

1. **No enforcement** — The system prompt said "don't modify infrastructure files" but the LLM could still read them via `read_file`, wasting a full turn.
2. **Permissive tool description** — `read_file` described itself as for "files referenced in the user's prompt" but didn't explicitly exclude infrastructure.
3. **Verbose prompt** — The system prompt used markdown formatting, conversational tone, and redundant examples that inflated input tokens and gave the LLM license to be verbose.
4. **No generation budget** — No line cap, no docstring ban, no test limit. The LLM maximized output.
5. **Heavy output format** — `### FILE:` + triple-backtick blocks added parsing overhead and didn't discourage prose between files.
6. **Redundant user message** — `build_user_message()` repeated tool-use instructions already in the system prompt.

## Changes

All changes in `mcp_servers/python/codegen/main.py`.

### 1. Server-side deny on infrastructure paths

Added a check at the top of `_execute_read_file()` that rejects any path whose filename matches `INFRASTRUCTURE_FILES`. Returns: `"ACCESS_DENIED: '<filename>' is a sealed infrastructure file and cannot be read."` This makes it impossible for the LLM to waste turns reading template files.

### 2. Tightened `read_file` tool description

Changed from generic "Read the contents of a file from the working directory" to explicit scoping: "Read a user-referenced file (criteria, specs, data). Only for files explicitly mentioned in the user prompt that are NOT already provided in the system prompt. Will reject infrastructure/scaffold files."

### 3. Rewrote system prompt with strict discipline

Restructured `build_system_prompt()` into focused sections:

- **Role** — one line: "You are a Python code generator. Output only code files, no prose."
- **Non-negotiables** — binary rules: no unnecessary tool calls, sealed infrastructure, no prose output
- **Runtime contract** — what `task.py` must export, available imports, tools.py signatures inline (no markdown fences)
- **Rules** — pure Python for scoring/formatting, .py only, Windows strftime
- **Generation budget** — under 800 lines total, max 10 tests per module, no docstrings on internal functions
- **Tool rules** — explicit gate: "You must not call read_file unless the user prompt explicitly mentions a filename you have not seen."
- **Output format** — compact `=== filename ===` delimiters, no markdown fences, no explanatory text

### 4. Updated `parse_files()` regex

Changed from matching `### FILE: <name>` + triple-backtick blocks to matching `=== <name> ===` delimiters. Added fallback stripping of markdown fences in case the LLM wraps code despite instructions.

### 5. Simplified `build_user_message()`

Reduced to `"Requirements:\n\n{user_prompt}"`. Removed redundant tool-use instructions — the system prompt already covers tool gating.

### 6. Updated validation fix prompt

Changed `_validate_code()` fix request from `### FILE:` format reference to `=== filename ===` format.

## Files Modified

- `mcp_servers/python/codegen/main.py` — all changes in this single file

## Expected Impact

- No `read_file` calls for infrastructure files (enforced server-side)
- Code generation completes in 1 turn when no user files are referenced (no wasted tool-use turn)
- Output tokens well under 16K (was hitting 32K limit)
- Tighter, more predictable generated code (line budget + no docstring bloat)

## Relationship to Prior Work

This builds on [PLAN-codegen-agentic-loop.md](PLAN-codegen-agentic-loop.md) which introduced the mini agentic loop and `read_file` tool. That plan solved the structural problem (brittle regex auto-detection). This plan tightens the behavioral problem (LLM wasting turns and generating bloat despite having the right tools).
