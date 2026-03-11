# Plan: Codegen Server — Hardening & Bug Fixes

**Status: Completed** (2026-03-11)

## Context

Code review of `mcp_servers/python/codegen/main.py` identified several issues ranging from a missing feature in validation fix rounds to minor correctness bugs. None are blocking, but several affect cost reporting accuracy and robustness under edge cases.

## Issues

### 1. Validation fix rounds don't support tool use or continuations

**File:** `main.py` lines 375–396
**Severity:** Medium
**Description:** During validation fix rounds, the LLM response is streamed and the text is extracted, but `_process_tool_calls()` is never called. If the LLM emits a `read_file` tool call during a fix round (e.g. to re-read a referenced file for context), the tool call is silently ignored and the conversation stalls or produces incomplete output. Similarly, `max_tokens` truncation is not handled — a long fix response is silently truncated.

**Fix:** Apply the same tool-dispatch and `max_tokens`-continuation logic from the main agentic loop (lines 506–521) inside `_validate_code`. Consider extracting the shared loop body into a helper.

---

### 2. Cache tokens not tracked during validation rounds

**File:** `main.py` lines 383–384
**Severity:** Low
**Description:** Validation fix rounds accumulate `input_tokens` and `output_tokens` but not `cache_creation_input_tokens` or `cache_read_input_tokens`. Since validation uses the same `cached_system` and `cached_tools`, cache hits will occur but won't be reflected in the final cost report. This causes cost reporting to undercount actual cache usage.

**Fix:** Track `cache_creation_input_tokens` and `cache_read_input_tokens` in `_validate_code` and return them alongside the existing token counts.

---

### 3. `run_task` output not truncated

**File:** `main.py` lines 676–677, 691–696
**Severity:** Low
**Description:** `run_task` captures the full stdout/stderr of the subprocess and serializes it into `structuredContent` without any size limit. A task that produces megabytes of output would bloat the tool result and potentially the LLM context. By contrast, validation output is already capped at 2000 chars (line 405).

**Fix:** Truncate stdout/stderr in the structured result (e.g. last 10,000 chars), keeping the full text in the `content` field if needed, or cap both.

---

### 4. Redundant exception nesting in `run_task`

**File:** `main.py` lines 664–685
**Severity:** Low (code clarity)
**Description:** `run_task` has a double `try/except` — the inner catches `TimeoutExpired`, the outer catches `Exception`. The outer handler is unnecessary since `subprocess.run` only raises `TimeoutExpired` or `SubprocessError` (already handled by the inner block). The nesting makes the control flow harder to follow.

**Fix:** Flatten to a single `try` block with `except TimeoutExpired` and `except Exception` handlers.

---

### 5. No cleanup of template directory on generation failure

**File:** `main.py` lines 439–531
**Severity:** Low
**Description:** If `generate_code` fails after copying the template (e.g. LLM error at line 530, npm install failure at line 568, no files parsed at line 546), the `tools/<task_name>/` directory is left behind. Over time this accumulates orphaned directories.

**Fix:** Consider cleaning up on error, or document that orphaned directories should be cleaned manually. A `try/except` with `shutil.rmtree` on the target directory would work, but risks deleting useful debug artefacts. A pragmatic middle ground: log a warning suggesting manual cleanup.

---

### 6. Non-atomic template copy with suffix collision

**File:** `main.py` lines 88–92
**Severity:** Low
**Description:** `copy_template` checks for directory existence then copies — a TOCTOU race. Two concurrent `generate_code` calls with the same `task_name` could both see the directory as absent and collide on `shutil.copytree`. Low probability in practice since codegen is user-initiated and sequential.

**Fix:** No immediate action needed. If concurrent codegen is ever supported, use a lock or atomic rename pattern.

## Priority

Issues 1–2 are the most impactful — they affect correctness (validation tool use) and cost accuracy (cache tracking). Issues 3–6 are minor improvements.
