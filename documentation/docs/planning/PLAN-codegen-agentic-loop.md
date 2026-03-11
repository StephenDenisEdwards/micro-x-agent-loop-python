# Plan: Codegen Server — Mini Agentic Loop with `read_file` Tool

**Status: Completed** (2026-03-02)

## Context

The codegen MCP server currently uses a single-shot LLM call with zero tools. To handle prompt files that reference other files (e.g. `job-search-prompt.txt` references `job-search-criteria.txt`), we added brittle regex-based auto-detection that scans for quoted filenames. This fails for indirect references and requires the server to guess what the LLM needs.

**The fix:** Give the codegen LLM a single `read_file` tool so it can read referenced files itself — same as the agent would in PROMPT mode. This is a constrained mini-loop (1 tool, focused system prompt, 10-turn limit), not the 59-tool chaos that motivated isolation. It also positions codegen to migrate naturally to a subagent architecture when that's added.

## Files Modified

- `mcp_servers/python/codegen/main.py` — replaced single-shot with agentic loop, added `run_task` tool
- `tools/template-py/utils.py` — added `append_file` function
- `documentation/docs/design/DESIGN-codegen-server.md` — updated architecture + rationale

## Implementation

### `main.py` Changes

**Added:**
- `MAX_TURNS = 10` — hard limit on loop iterations
- `READ_FILE_TOOL` — tool schema dict for `read_file(path)`
- `_execute_read_file(path)` — resolves path relative to WORKING_DIR, validates containment via `.resolve()` + `.relative_to()`, returns file content or error string
- `_process_tool_calls(response)` — iterates `tool_use` blocks, executes `read_file`, returns `tool_result` list
- `build_system_prompt(task_name, tools_py)` — static instructions (role, template context, tools.py content, output format, constraints). Includes Windows strftime rule and `write_file`/`append_file` documentation.
- `build_user_message(user_prompt)` — user requirements + instruction to read referenced files
- `run_task(task_name)` — runs a generated app via `python -m tools.<task_name>` from PROJECT_ROOT with 300s timeout

**Deleted:**
- `_detect_referenced_files()` — regex auto-detection no longer needed
- `_read_context_files()` — LLM reads files itself via `read_file`
- `build_prompt()` — replaced by `build_system_prompt()` + `build_user_message()`

**Rewritten:**
- `generate_code()` — now takes inline `prompt` text (not `prompt_file`). Agentic loop: copy template → build messages → loop (stream API call, process tool calls, break on end_turn) → parse FILE: blocks → write files. Uses streaming to avoid SDK timeout. Dropped `context_files` parameter — LLM fetches what it needs.

**Kept unchanged:**
- `_error_result()`, `copy_template()`, `parse_files()`

### `utils.py` Template Changes

- Added `append_file(path, content, config)` — appends to file instead of overwriting
- Extracted `_resolve_path()` helper shared by `write_file` and `append_file`
- `write_file` docstring clarified as "(overwrites)"

### Codegen System Prompt Rules Added

- Windows strftime: do not use `%-d`, `%-m` etc. (Unix-only)
- `write_file` overwrites, `append_file` appends — use correctly for staged writing
- Read referenced files via `read_file` before generating code

### Security

`_execute_read_file` prevents path traversal:
- Resolve path relative to WORKING_DIR
- `.resolve()` canonicalizes (handles `..`, symlinks)
- `.relative_to(WORKING_DIR.resolve())` verifies containment
- Returns error string (not exception) for non-existent files or traversal attempts

`run_task` constraints:
- 300-second timeout prevents runaway apps
- Only runs from PROJECT_ROOT via `python -m tools.<task_name>`
- Validates `task.py` exists before execution

## Verification

Tested with `job-search-prompt.txt` which references `job-search-criteria.txt`:
- LLM completed in 3 turns (read criteria file, then generated code)
- 4 files written: `task.py`, `collector.py`, `scorer.py`, `processor.py`
- 24K input / 18K output tokens
- Generated code uses actual criteria from the file, not hardcoded guesses
- App ran end-to-end, produced correct report

Tested with inline prompt (email summary app):
- Agent passed prompt text directly — no prompt file needed
- Code generated and ran successfully via `run_task`

## Bugs Fixed During Implementation

1. **Windows strftime** — generated code used `%-d` (Unix-only), crashed with `ValueError` on Windows. Fixed by adding rule to codegen system prompt.
2. **File overwrite** — `write_file` always overwrites; generated code tried to write report in stages but each call overwrote the previous. Fixed by adding `append_file` to template `utils.py` and documenting both in the codegen prompt.
3. **Agent couldn't run generated apps** — outer agent tried `python task.py` directly, failed on relative imports. Fixed by adding `run_task` tool that handles the correct invocation.
