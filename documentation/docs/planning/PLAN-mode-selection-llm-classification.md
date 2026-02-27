# Plan: Mode Selection — Phase 2 LLM Classification

## Status

**Completed**

## Context

Phase 1 (complete) implements Stage 1 structural pattern matching — zero-cost regex-based signal detection that routes clear cases directly to COMPILED or PROMPT. Ambiguous cases (1 strong signal, or only moderate/supportive signals) currently default to PROMPT, which measured data shows can be 4–20x more expensive than compiled mode for batch tasks.

Phase 2 adds Stage 2: a cheap LLM classification call for AMBIGUOUS cases only. The LLM receives the user's prompt and Stage 1 signals, then recommends PROMPT or COMPILED. This costs ~$0.01 per call. Given measured prompt-mode costs of $0.79+ for batch tasks, even modest classification accuracy provides strongly positive ROI.

Like Phase 1, this is **diagnostic output only** — it prints the recommendation but does not change execution behaviour.

## Phased Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 — Mode selection CLI output | Structural pattern matching, diagnostic output only | **Complete** |
| **2 — LLM classification** | **Cheap LLM call for ambiguous cases, diagnostic output** | **Complete** |
| 3 — `agent_mcp` client library | Bridge library for generated code to call MCP servers | Future |
| 4 — Code generation and sandbox execution | LLM writes programs against MCP servers, sandbox runs them | Future |
| 5 — Narrative callback | LLM returns for prose from compact results | Future |

## Implementation Plan

### Step 1: Add Stage 2 functions to `mode_selector.py`

**File:** `src/micro_x_agent_loop/mode_selector.py`

Keep mode_selector.py as pure computation — no async, no provider dependency. Add:

- `Stage2Result` dataclass (frozen) with `recommended_mode` and `reasoning`
- `build_stage2_prompt(user_message, stage1)` — builds the classification prompt with the user's message, Stage 1 signals, and guidance
- `parse_stage2_response(response_text)` — extracts PROMPT/COMPILED from LLM response, defaults to COMPILED on parse failure (asymmetric cost)
- `format_stage2_result(result)` — formats as `[Mode Analysis] Stage 2 override: ...`

### Step 2: Add config fields

- `AgentConfig`: `stage2_classification_enabled: bool`, `stage2_model: str`
- `AppConfig`: same fields, parsed from `Stage2ClassificationEnabled` (default `True`) and `Stage2Model` (default `""` = use main model)

### Step 3: Wire config through `bootstrap.py`

Pass `stage2_classification_enabled` and `stage2_model` from `AppConfig` to `AgentConfig`.

### Step 4: Add Stage 2 classification to `agent.py`

- Store config fields in `__init__`
- `_classify_ambiguous()` method: calls `build_stage2_prompt` → `provider.create_message` (temperature=0.0, max_tokens=300) → `parse_stage2_response`, logs usage via `on_api_call_completed`
- Update `_run_inner()`: when Stage 1 returns AMBIGUOUS and Stage 2 is enabled, call `_classify_ambiguous` inside try/except so failures don't abort the turn

### Step 5: Tests

Unit tests for pure functions (prompt construction, response parsing, formatting) plus agent integration tests covering all four plan scenarios and error handling.

## Files Modified

| File | Change |
|---|---|
| `src/micro_x_agent_loop/mode_selector.py` | Add `Stage2Result`, `build_stage2_prompt()`, `parse_stage2_response()`, `format_stage2_result()` |
| `src/micro_x_agent_loop/agent_config.py` | Add `stage2_classification_enabled`, `stage2_model` |
| `src/micro_x_agent_loop/app_config.py` | Add `stage2_classification_enabled`, `stage2_model` with parsing |
| `src/micro_x_agent_loop/bootstrap.py` | Pass Stage 2 config through to `AgentConfig` |
| `src/micro_x_agent_loop/agent.py` | Add `_classify_ambiguous()`, update `_run_inner()` with try/except |
| `tests/test_mode_selector.py` | Add `Stage2PromptTests`, `Stage2ResponseParsingTests`, `Stage2FormatTests`, `Stage2AgentIntegrationTests` |

## Verification

Tested live in REPL and via 16 new tests (10 unit + 6 integration), 344 total passing:

| Prompt | Stage 1 | Stage 2 |
|---|---|---|
| "What's the weather in London?" | PROMPT | skipped |
| Full job search prompt | COMPILED | skipped |
| "List the last 50 emails from JobServe..." | AMBIGUOUS | COMPILED ($0.0014) |
| "Score this document for readability" | AMBIGUOUS | PROMPT |
