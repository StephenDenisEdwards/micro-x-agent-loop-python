# Plan: Codegen Server — Mini Agentic Loop with `read_file` Tool

**Status: Completed** (2026-03-02)

## Context

The codegen MCP server currently uses a single-shot LLM call with zero tools. To handle prompt files that reference other files (e.g. `job-search-prompt.txt` references `job-search-criteria.txt`), we added brittle regex-based auto-detection that scans for quoted filenames. This fails for indirect references and requires the server to guess what the LLM needs.

**The fix:** Give the codegen LLM a single `read_file` tool so it can read referenced files itself — same as the agent would in PROMPT mode. This is a constrained mini-loop (1 tool, focused system prompt, 10-turn limit), not the 59-tool chaos that motivated isolation. It also positions codegen to migrate naturally to a subagent architecture when that's added.

## Files Modified

- `mcp_servers/python/codegen/main.py` — replaced single-shot with agentic loop
- `documentation/docs/design/DESIGN-codegen-server.md` — updated architecture + rationale

## Implementation

### `main.py` Changes

**Added:**
- `MAX_TURNS = 10` — hard limit on loop iterations
- `READ_FILE_TOOL` — tool schema dict for `read_file(path)`
- `_execute_read_file(path)` — resolves path relative to WORKING_DIR, validates containment via `.resolve()` + `.relative_to()`, returns file content or error string
- `_process_tool_calls(response)` — iterates `tool_use` blocks, executes `read_file`, returns `tool_result` list
- `build_system_prompt(task_name, tools_py)` — static instructions (role, template context, tools.py content, output format, constraints)
- `build_user_message(user_prompt, context_files_text)` — user requirements + pre-loaded context files + instruction to read referenced files

**Deleted:**
- `_detect_referenced_files()` — regex auto-detection no longer needed
- `build_prompt()` — replaced by `build_system_prompt()` + `build_user_message()`

**Rewritten:**
- `generate_code()` — agentic loop: validate → copy template → read context → loop (stream API call, process tool calls, break on end_turn) → parse FILE: blocks → write files. Uses streaming to avoid SDK timeout on long generations. Structured result includes `turns` field.

**Kept unchanged:**
- `_error_result()`, `copy_template()`, `parse_files()`, `_read_context_files()`, `context_files` parameter

### Security

`_execute_read_file` prevents path traversal:
- Resolve path relative to WORKING_DIR
- `.resolve()` canonicalizes (handles `..`, symlinks)
- `.relative_to(WORKING_DIR.resolve())` verifies containment
- Returns error string (not exception) for non-existent files or traversal attempts

## Verification

Tested with `job-search-prompt.txt` which references `job-search-criteria.txt`:
- LLM completed in 3 turns (read criteria file, then generated code)
- 4 files written: `task.py`, `collector.py`, `scorer.py`, `processor.py`
- 24K input / 18K output tokens
- Generated code uses actual criteria from the file, not hardcoded guesses
