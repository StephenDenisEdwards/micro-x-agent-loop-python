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

### 7. Reject filenames with path separators in `parse_files()`

Added a check that skips any filename containing `/` or `\`. All generated files must be flat in the target directory. Without this, the LLM can generate paths like `tools/__init__.py` during fix rounds, which resolves to a non-existent subdirectory and crashes the file writer.

## Pre-Fix Failure Analysis

Observed on a job search app generation run (pre-fix). The LLM (Sonnet 4.6) used **5 turns**, **47K output tokens**, and the generated app didn't work.

### Issue 1: Infrastructure file reads wasted 2 turns

The LLM read `__main__.py`, `llm.py`, `utils.py`, and `tools.py` across turns 1-2 — all files whose content was already in the system prompt. This consumed ~15K input tokens for zero value.

**Fixed by:** Change 1 (server-side deny in `_execute_read_file`).

### Issue 2: 47K output tokens, hit max_tokens twice

With no generation budget, the LLM produced 2,724 lines across 7 files — 3.4x over the 800-line budget. It hit the 16K max_tokens ceiling on turns 3 and 4, requiring continuation turns.

**Fixed by:** Change 3 (generation budget: 800 lines, 10 tests/module, no internal docstrings).

### Issue 3: Corrupted file from max_tokens split

`test_scorer.py:166` contained `"ir35### FILE: test_scorer.py` — a `### FILE:` delimiter that landed mid-string when max_tokens cut the response. The old `parse_files` regex matched this marker inside truncated content and created a corrupt file with a syntax error.

**Fixed by:** Change 4 (new `=== filename ===` format) + Change 3 (budget prevents overflow). The compact format with no markdown fences is less likely to appear in code strings, and the budget means the LLM should complete in 1 turn without hitting max_tokens.

### Issue 4: Validation crash on subdirectory filename

During fix round 2, the LLM generated a file with a subdirectory path (e.g. `tools/__init__.py`). This resolved to `tools/job_search/tools/__init__.py` — the parent directory doesn't exist, so `write_text()` threw `FileNotFoundError` and crashed the validation phase.

**Fixed by:** Change 7 (reject filenames with `/` or `\` in `parse_files()`).

### Aggregate cost

| Metric | Value |
|--------|-------|
| Turns | 5 (2 wasted on infra reads, 2 on max_tokens continuations) |
| Output tokens | 47,098 |
| Input tokens | 58,356 (incl. cache) |
| Estimated cost | $0.90 |
| Generated lines | 2,724 |
| Working app? | No |

With the fixes applied, expected outcome: 1 turn (or 2 if user file referenced), <16K output tokens, <800 lines, working validation.

## Expected Impact

- No `read_file` calls for infrastructure files (enforced server-side)
- Code generation completes in 1 turn when no user files are referenced (no wasted tool-use turn)
- Output tokens well under 16K (was hitting 32K limit)
- Tighter, more predictable generated code (line budget + no docstring bloat)
- No crashes from subdirectory filenames in LLM output

## Relationship to Prior Work

This builds on [PLAN-codegen-agentic-loop.md](PLAN-codegen-agentic-loop.md) which introduced the mini agentic loop and `read_file` tool. That plan solved the structural problem (brittle regex auto-detection). This plan tightens the behavioral problem (LLM wasting turns and generating bloat despite having the right tools).
