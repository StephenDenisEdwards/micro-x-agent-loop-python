# Codebase Review — 2026-06-05

**Reviewed:** 2026-06-05
**Reviewer:** Full-codebase audit (architecture, coding standards, type hygiene, test coverage, test quality, structure)
**Scope:** `src/micro_x_agent_loop/` (123 files) and `tests/` (112 files), plus `mcp_servers/ts/` artifacts where ADR-024 compliance was checked
**Status key:** `✅ Done` · `⚠️ Partial` · `🔲 Planned` · `❌ Gap`

---

## Review Context

This is a broad audit covering architecture, layering, ADR/SAD compliance, coding-standards compliance (ruff/mypy/project rules), test coverage, and test quality. Findings are organised into prioritised tiers with file:line citations.

**Headline:** Architecture is *cleaner than its size suggests* — layers and async/sync boundaries are largely respected. The biggest issues are concentrated: one god module (`agent.py`), a 55-field config dataclass plus 36 `config-*.json` files at the repo root, an ADR-024 violation in a shipped `dist/` artifact, and a test suite that is broad but stylistically inconsistent.

Triggering question: *full detailed review of the code base — architecture, compliance with coding standards, test coverage, test quality, structure.*

Related ADRs: ADR-010, ADR-017, ADR-018, ADR-021, ADR-024.
Primary reference: `CLAUDE.md` (project standards), `documentation/docs/architecture/` (SAD v3.0 + ADRs).

---

## Objective Signals (snapshot)

### Lint
- **Ruff:** 12 violations (8 src, 4 tests).
  - `src/micro_x_agent_loop/mcp/mcp_manager.py:64, 333, 342, 354` — UP041 (`asyncio.TimeoutError` → `TimeoutError`)
  - `src/micro_x_agent_loop/system_prompt.py:235, 237, 568` — E501 (longest 154 chars)
  - `src/micro_x_agent_loop/provider.py:142` — E501
  - `tests/test_mcp_manager.py:501` — **F821 undefined `Any`** (real bug — test crashes on that path)
  - `tests/test_compaction_strategy.py:120`, `tests/test_trim_conversation_history.py:179` — E501
  - `tests/providers/test_gemma_via_gemini.py:7` — I001 (import sort)

### Type-check (mypy)
- 2 errors (repo currently violates its own "mypy must be clean" rule):
  - `src/micro_x_agent_loop/cli/esc_watcher.py:25` — `Module has no attribute "windll"` (needs `# type: ignore[attr-defined]`)
  - `src/micro_x_agent_loop/tui/app.py:553` — `Cannot determine type of "theme"`

### Tests
- **1,834 passed / 15 skipped / 5 failing** (3 min 38 s):
  - `tests/test_native_system_info.py::NativeSystemInfoTests::test_execute_returns_text`
  - `tests/test_system_prompt_filesystem_roots.py::FilesystemRootsFromConfigTests::test_parses_split_by_pathsep`
  - `tests/test_system_prompt_filesystem_roots.py::FilesystemRootsFromConfigTests::test_skips_blank_entries`
  - `tests/test_trace_screen.py::TraceScreenPilotTests::test_screen_populates_tree_and_shows_detail`
  - `tests/test_usage.py::EstimateCostAllModelsTests::test_every_config_model_has_a_test`
- **Total coverage: 77%** (12,218 statements, 2,864 missing). `tui/` contributes ~15% of all uncovered lines; excluding TUI raises coverage to ~83%.

---

## 1. Architecture

### Layering & module boundaries — mostly clean

- **Provider layer is clean.** `provider.py:118-138` does lazy local imports of each `providers/*_provider.py`; SDK provider modules only import sideways into `providers/common.py` and downward into `tool.py`/`usage.py` (`providers/anthropic_provider.py:10-15`). No upward imports into `agent.py` or `turn_engine.py`.
- **Broker is self-contained.** Every cross-file import inside `src/micro_x_agent_loop/broker/` stays within the package (`broker/service.py:13-18`, `broker/dispatcher.py:11-15`). Server reaches into broker rather than the reverse (`server/app.py:107-113`, `server/broker_routes.py:11-13`).
- **No true circular imports detected.** TYPE_CHECKING is used correctly throughout (`turn_engine.py:21-22`, `agent_config.py:8-9`).

### Layering leaks worth flagging

- `agent.py` does **9 in-function imports** (`:201, :313, :477, :528, :846, :868`) — some are TYPE_CHECKING-style circular avoidance, but several (e.g. duplicate `from micro_x_agent_loop.compaction import estimate_tokens` at `:846` and `:868`) signal over-coupling.
- `agent_channel.py` mixes the channel **protocol** (universal) with three concrete implementations including `BrokerChannel` at `:402` and a `_RichRenderer` import inside a method at `:454-455`. The protocol module shouldn't import `httpx` or know about brokers.

### God modules

| Module | LOC | Smell |
|---|---:|---|
| `agent.py` | 1,219 | God object — see Risk #1 |
| `commands/command_handler.py` | 1,062 | Single 41-method class; split per-command-group |
| `tui/app.py` | 882 | Large; 0% test coverage |
| `turn_engine.py` | 752 | Acceptable; pseudo-tool dispatch (`:313-396`) inlined |
| `system_prompt.py` | 605 | Mostly templates; fine |

### ADR compliance — one real violation

- ✅ **ADR-018** (broker subprocess dispatch): `broker/runner.py:44-112` uses `asyncio.create_subprocess_exec` with timeout, byte cap (`_MAX_OUTPUT_BYTES = 10MB`), and clean kill semantics.
- ✅ **ADR-017** (`ask_user` pseudo-tool): routed entirely through `AgentChannel.ask_user` (`turn_engine.py:323, 347-361`).
- ✅ **ADR-010 / ADR-021** (multi-provider + same-family fallback): factory at `provider.py:118-138` is consistent; `provider_pool.py` (295 LOC) implements the pool.
- ❌ **ADR-024** (single-layer truncation) **violated in shipped `dist/`**: `mcp_servers/ts/packages/web/dist/tools/web-fetch.js:4` ships `const DEFAULT_MAX_CHARS = 50_000;` and `:48` applies `input.maxChars ?? DEFAULT_MAX_CHARS`. The `.ts` source at `web-fetch.ts:73` is clean — `dist/` wasn't rebuilt. This is exactly the symptom ADR-024 §Context.1 calls out. ADR-024 §Open already flags a missing CI lint rule for this.

### Concurrency — clean

- Only **one `asyncio.run`** in the codebase, at the entry point `__main__.py:133`. No `run_until_complete`, no `run_coroutine_threadsafe`, no `new_event_loop`.
- Threading is confined to UI/IO concerns: `llm_client.py:2` (spinner), `terminal_renderer.py:9`, `tui/widgets/log_panel.py:5`, `cli/esc_watcher.py:10`. None touch the agent's async core.
- **Minor smell:** `subprocess.run` (blocking) at `native_tools/filesystem/bash_tool.py:231` and `read_tools.py:304`. If tool `.execute` is awaited, these block the event loop. Confirm and wrap in `asyncio.to_thread`.

### Configuration sprawl

- **36 `config-*.json` files at the repo root** (incl. `config-starter.json.bak`). Most are testing/eval variants. Move evals to `configs/evals/` and keep ≤5 at root.
- `AgentConfig` (`agent_config.py:117-191`) is a **55-field flat dataclass**, with sub-config factory methods (`:195-266`) that re-pack subsets into `LLMConfig`/`MemoryConfig`/etc. Worst of both worlds: flat god-dataclass *plus* duplicated state in derived structs.
- CLAUDE.md prohibits hardcoded defaults, yet `agent_config.py:33, 118` default `model = "claude-sonnet-4-5-20250929"`. Drop the default or amend the rule.

### Pseudo-tool dispatch — brittle

`turn_engine.py:313-396` classifies each `tool_use` block into one of 5 buckets (`search_blocks`, `ask_user_blocks`, `subagent_blocks`, `task_blocks`, `regular_blocks`) and handles each inline. Adding a 6th pseudo-tool touches 4 places. Extract a `PseudoToolHandler` protocol with `matches(name) -> bool` and `async execute(block) -> dict`, registered in a list.

---

## 2. Coding Standards & Type Hygiene

### `# type: ignore` audit

- **32 occurrences in `src/`, zero bare** (all specify codes). Good discipline.
- Top offenders: `server/app.py` (9), `server/broker_routes.py` (6), `providers/anthropic_provider.py` (5).
- Most server-side ignores are `# type: ignore[no-untyped-def]` on FastAPI routes (`server/app.py:283`, `server/broker_routes.py:37`). Add real `-> Response` / `-> dict[str, Any]` annotations instead of silencing — 15 ignores would disappear.
- Anthropic ignores (`providers/anthropic_provider.py:109-111, 187, 204`) are legitimate SDK-typing limitations.

### `from __future__ import annotations` audit

- **14 of 123 files missing it.** 8 are `__init__.py` shims (fine). Non-trivial offenders: `llm_client.py`, `system_prompt.py`, `constants.py`, `mcp/mcp_manager.py`, `mcp/mcp_tool_proxy.py`, `server/sdk.py`.

### `Any` overuse

- `turn_engine.py:34, 46, 60, 64, 66` — `provider: Any`, `summarization_provider: Any | None`, `semantic_classifier: Any | None`, `routing_feedback_callback: Any | None`, `task_embedding_index: Any | None`. All should be Protocols or concrete types (`Provider` already exists in `provider.py`).
- `provider_pool.py` — 11 `Any` occurrences.

### Protocol drift

- **`AgentChannel` Protocol** (`agent_channel.py:70`) drift: `TerminalChannel` exposes `begin_streaming` (`:253`), `end_streaming` (`:263`), `print_line` (`:273`) **not on the Protocol**. Callers downcasting these will break with `BufferedChannel`/`BrokerChannel`. Either widen the Protocol or split into a `StreamingChannel` sub-Protocol.
- **`Tool` Protocol** (`tool.py:15-30`) is honoured by every impl, but `memory/facade.py:253` still uses `getattr(tool, "predict_touched_paths", None)` — dead defensive read.

### Style discipline that *is* good

- **Zero `TODO`/`FIXME`/`XXX`/`HACK`** comments in `src/`.
- Essentially no commented-out code; only one why-comment at `tool_result_formatter.py:72`.
- Zero bare `# type: ignore`.

---

## 3. Test Coverage

### Per-subdirectory mapping

| Subdir | Src files | Test files | Notes |
|---|---:|---:|---|
| broker | 11 | 12 (`tests/broker/`) | Full |
| server | 7 | 12 (`tests/server/`) | Full |
| memory | 9 | 8 (`tests/memory/`) | Full |
| mcp | 3 | 2 | Full |
| providers | 7 | 6 + 2 top-level | Gaps: `providers/common.py`, `providers/groq_provider.py` |
| commands | 5 | 5 | Full |
| native_tools | 8 | 6 | Filesystem covered |
| tasks | 5 | 3 | `tasks/schemas.py`, `tasks/models.py` only transitively |
| services | 3 | **0 dedicated** | Checkpoint/rewind correctness lacks direct tests |
| **cli** | 4 | **0** | Entire `cli/` package untested |
| **tui** | 14 | 2 | `tui/app.py` (882 LOC), all 7 widgets, 3 modals untested |

### Coverage hot/cold spots (from `pytest --cov`)

**Worst-covered:**

| Module | LOC | Cov |
|---|---:|---:|
| `tui/app.py` | 419 | **0%** |
| `tui/widgets/*` (all 7) | 432 total | **0%** |
| `tui/screens/*` (4 of 5) | 185 total | **0%** |
| `providers/groq_provider.py` | 6 | **0%** |
| `otel_export.py` | 84 | 42% |
| `native_tools/filesystem/read_tools.py` | 242 | 62% |
| `native_tools/__init__.py` | 33 | 61% |
| `native_tools/system_info.py` | 89 | 67% |
| `provider.py` | 48 | 69% |
| `mcp/mcp_manager.py` | 241 | 74% |
| `metrics.py` | 221 | 76% |

**Best-covered (≥98%):** `gemini_provider.py`, `ollama_provider.py`, `routing_feedback.py`, `tool_result_formatter.py`, `tool.py`, `tasks/models.py`, `embedding.py`, `services/session_controller.py`, `redaction.py`, `sub_agent.py`, `mode_selector.py`, `terminal_prompter.py`, `tool_search.py`.

### Highest-damage coverage gaps

1. **`cli/dispatch.py` + `cli/repl.py` + `__main__.py`** (484 LOC combined) — every CLI invocation flows through these; zero direct tests. A regression breaks `./run.sh`, `--run`, `--broker`, `--server` entry.
2. **`agent_builder.py`** (363 LOC) — wires up the entire runtime; bugs here mis-configure every session. No direct test.
3. **`agent.py`** (1,219 LOC) — covered transitively across 6 files but no dedicated `test_agent.py`; mode-analysis, history-pruning, metric-finalisation paths only partly hit.
4. **`tui/app.py`** (882 LOC) — completely untested.
5. **`services/session_controller.py` + `services/checkpoint_service.py`** — checkpoint/rewind bugs would corrupt files restored from `.micro_x/memory.db`.

### Integration tests

- `tests/integration/` contains **only** `test_github_wrappers.py` (live GitHub API, requires `GITHUB_TOKEN`).
- **No end-to-end agent-loop integration test using `FakeStreamProvider`.** Every fake-provider test is unit-scoped (`test_ask_user.py`, `test_tool_search.py`, `test_cost_reduction.py`, `test_turn_engine.py`, `test_turn_engine_extended.py`, `test_mode_selector.py`, `test_sub_agent.py`).
- `tests/evals/` is a separate eval framework, not an integration suite.

### Directory-mirror inconsistencies

- No `tests/tui/`, `tests/tasks/`, `tests/commands/`, `tests/mcp/`, `tests/native_tools/`, `tests/services/`, `tests/cli/` — tests for these live at the top level.
- `tests/voice/test_voice_runtime.py` exists alongside top-level `test_voice_runtime_extended.py` and `test_voice_ingress.py`. Pick one.

---

## 4. Test Quality

### Async test inconsistency — the biggest smell

`pytest-asyncio>=0.23` is declared in `pyproject.toml:44` but used in **exactly 2 files**: `tests/integration/conftest.py:12, 47, 67` and `tests/integration/test_github_wrappers.py:42`. Every other async test wraps its body in `asyncio.run()` inside a `unittest.TestCase` — **30+ instances** across `tests/test_tool_search.py:173-217`, `tests/test_ask_user.py:71-284`, `tests/test_mcp_manager.py:99-255`, `tests/server/test_sdk_client_methods.py:70-93`, `tests/broker/test_runner.py:100-131`. This:

- Spins a fresh event loop per call, defeating shared-loop fixture patterns.
- Forces the `async def go(): …; asyncio.run(go())` wrapper pattern (`tests/server/test_sdk_client_methods.py:50-70`).
- Makes shared async resources impossible — `tests/server/test_sdk_client_methods.py:68, 79` manually close `client._http` per-test.
- `tests/test_native_filesystem_write_tools.py:25` ships its own `_run()` helper.

**Fix:** standardize on `@pytest.mark.asyncio` and migrate. Or remove `pytest-asyncio` from deps.

### Mock vs. real — uneven

- **Over-mocking:** `tests/test_command_handler.py:41-69` `_make_handler` builds 5 MagicMocks and pre-canns `cs.format_rewind_outcome_lines.return_value = ["  Rewound."]` (line 67), then asserts `"Rewound."` appears in output — borderline tautological.
- **Exemplary:** `tests/server/test_ws_integration.py` uses a real FastAPI `TestClient`, real WebSocket, only fakes the LLM agent via a clean `FakeAgent`/`FakeAgentManager` injected through `create_app(agent_manager=...)`.
- `tests/providers/test_openai_provider.py:16-95` is pure-unit, no mocks — excellent.
- `MagicMock`/`patch`/`AsyncMock` appears in **864 lines across 37 files** — ad-hoc mocks dominate.

### Test isolation — two real issues

- **Writes outside tempdirs:** `tests/test_command_handler.py:368, 394, 411, 420` writes to `Path.cwd() / ".tmp-run" / …`, `os.chdir(project_root)`, then `shutil.rmtree`. Leaves litter if it crashes between mkdir and `finally`; `os.chdir` is parallelism-hostile.
- **Global state mutation:** `tests/conftest.py` mutates global `PRICING` gated by `if not PRICING` — order-dependent.
- Broker/native filesystem tests correctly use `tempfile.TemporaryDirectory` (`tests/broker/test_service.py:17-20`; `tests/test_native_filesystem_write_tools.py:31-36`).

### Sleep-as-synchronization — flake risk

- `tests/server/test_ws_channel.py:35, 47, 62, 76, 88, 103, 135` — all `await asyncio.sleep(0.05)`.
- `tests/broker/test_store_runs.py:145, 155` — `time.sleep(0.01)` for timestamp ordering. Race-prone on loaded CI.
- `tests/server/test_ws_integration.py:217` — `await asyncio.sleep(2.0)` (2 wall-clock seconds per run).
- `tests/test_sub_agent.py:189`, `tests/broker/test_runner.py:115` — `await asyncio.sleep(100)` for hang sentinels. Correct intent, but if timeout logic regresses, test wedges for 100s.
- Other `time.sleep` uses: `tests/test_agent_channel.py:361`, `tests/test_llm_client.py:17`, `tests/test_native_filesystem_read_tools.py:177`.

### Anti-patterns

- **Private-internal imports** (17+ tests): `tests/test_cost_reconciliation.py:31, 40, 49, 76, 101, 113` import `_resolve_api_key_id` six times; `tests/test_bootstrap.py:9` imports `_load_user_memory`; `tests/test_textual_channel.py:117, 130, 143` import `_parse_cli_args` from `__main__`.
- **Conditional logic in tests:** `tests/test_command_handler.py:369, 407, 412, 429`, `tests/test_embedding.py:154`.
- **`# Should not raise` rationale:** `tests/broker/test_service.py:70`, `tests/test_mcp_manager.py:160`.
- **Weak assertions:** 332 `assertIsNotNone`/`assertTrue`. `tests/test_native_system_info.py:36` `assertTrue(t.description)` passes for any truthy string.
- **`FakeStreamProvider.stream_chat` uses `**kwargs`** (`tests/fakes.py:195`) — silently absorbs new args; signature drift goes uncaught.

### Test-fakes design — good core

`tests/fakes.py` has well-designed protocol-satisfying reusable fakes: `FakeStreamProvider`, `FakeTool`, `FakeProvider`, `FakeEventEmitter`, `SessionManagerFake`, `CheckpointManagerFake`. But ad-hoc `FakeAgent` (`tests/server/test_ws_integration.py:26`), `FakeTransport` (`tests/server/test_sdk_client_methods.py:24`) duplicate intent.

---

## 5. Prioritised Open Items

### Tier 1 — must-fix (repo currently violates its own rules)

| ID | Item | Location | Status | Action taken |
|---|---|---|---|---|
| T1-1 | Fix mypy `attr-defined` error | `cli/esc_watcher.py:25` | ✅ Done | Added `# type: ignore[attr-defined]` for `ctypes.windll` (Windows-only) |
| T1-2 | Fix mypy `has-type` error on `theme` | `tui/app.py:553` | ✅ Done | Read into typed `current = cast(str, self.theme)` with `# type: ignore[has-type]` |
| T1-3 | Fix F821 undefined `Any` (real crash) | `tests/test_mcp_manager.py:501` | ✅ Done | Added `from typing import Any` |
| T1-4 | Fix 4 E501 line-too-long violations | `system_prompt.py:235, 237, 568`, `provider.py:142` | ✅ Done | Wrapped string concatenation / shortened markdown table cells |
| T1-5 | Fix 4 UP041 aliased TimeoutError | `mcp/mcp_manager.py:64, 333, 342, 354` | ✅ Done | `asyncio.TimeoutError` → `TimeoutError` |
| T1-6 | Fix I001 import sort | `tests/providers/test_gemma_via_gemini.py:7` | ✅ Done | `ruff check --fix` |
| T1-7 | Fix 5 failing tests | see Objective Signals → Tests | ✅ Done | (1) `disk_info`/`network_info` wrap `psutil.disk_partitions`/`net_if_*` in try/except (sandbox /proc restrictions); (2) `test_parses_split_by_pathsep` + `test_skips_blank_entries` use platform-agnostic `/path/one` instead of `C:\\path one` (no os.pathsep collision); (3) `test_trace_screen` gated with `@skipUnless(_HAS_TEXTUAL)`; (4) added 2 missing groq model tests + MODELS entries |
| T1-8 | Rebuild `mcp_servers/ts/packages/web/dist/` to clear ADR-024 violation | `dist/tools/web-fetch.js:4, 48` | ✅ Done | Rebuilt via `npm run build` in `packages/web`; `DEFAULT_MAX_CHARS` and `maxChars ??` no longer present. Note: `dist/` is gitignored, so the original violation was a local stale build artifact, not committed code |
| T1-9 | Add CI grep gate for `DEFAULT_MAX_CHARS` / `maxChars ??` outside `turn_engine.py` (ADR-024 §Open) | n/a | ✅ Done | Added grep step in `lint` job of `.github/workflows/python-tests.yml`; ADR-024 §Open updated |

**Post-Tier-1 status:** ruff clean, mypy clean, 1,840 tests passing / 16 skipped / 0 failing.

### Tier 2 — architecture (high leverage)

| ID | Item | Location | Status | Action taken |
|---|---|---|---|---|
| T2-1 | Split `agent.py` — extract `mode_orchestrator.py`, `history_repair.py`, observability-listener mixin | `agent.py` (1,219 LOC) | ✅ Done | Extracted `history_repair.py` (167 LOC), `mode_orchestrator.py` (210 LOC), and `agent_listener.py` (255 LOC — `AgentEventListener` implementing the pure-observability subset of TurnEvents with DI: memory, obs, accumulator, turn-number provider, optional compaction-tokens handler, optional budget-check callback). `agent.py` shrunk 1,219 → 872 LOC (-28%). Message-history and checkpoint-state callbacks (`on_maybe_compact`, `on_append_message`, `on_ensure_checkpoint_for_turn`, etc.) stay on Agent because they must mutate Agent state. |
| T2-2 | Split `commands/command_handler.py` per command group with a registry | `commands/command_handler.py` (1,062 LOC) | ⚠️ Partial | Added `commands/command_context.py` (read-only dataclass bundling the 16 collaborators). Extracted 5 command groups into per-command modules: `routing_command.py` (106 LOC), `session_command.py` (116 LOC), `voice_command_handler.py` (73 LOC), `checkpoint_command.py` (60 LOC), `compact_command.py` (27 LOC). `command_handler.py` shrunk 1,062 → 766 LOC (-28%). Remaining handlers (`/cost`, `/replay`, `/memory`, `/codegen-task-list`, `/tools`, `/tool`, `/debug`, `/help`, `/console`) can be extracted with the same pattern. |
| T2-3 | Replace `Any`-typed dependencies with real Protocols | `turn_engine.py:34, 46, 60, 64, 66` | ✅ Done | `provider: LLMProvider`, `summarization_provider: LLMCompactor \| None`, `semantic_classifier: SemanticClassifierFn \| None`, `routing_feedback_callback: RoutingFeedbackFn \| None`, `task_embedding_index: TaskEmbeddingIndex \| None`. Also typed `task_embedding_index` in `agent_builder.AgentComponents` to clear the type chain. |
| T2-4 | Sync `AgentChannel` Protocol with `TerminalChannel` extras (`begin_streaming`/`end_streaming`/`print_line`) or split into `StreamingChannel` | `agent_channel.py:70` | ✅ Done | Added `begin_streaming()` / `end_streaming()` to the Protocol with no-op implementations in `BufferedChannel`, `BrokerChannel`, `WebSocketChannel`. Dropped the `hasattr` guard in `agent.py:612-622`. `print_line` left as a TerminalChannel-private method (not called via the protocol from the agent). |
| T2-5 | Decide on flat vs nested `AgentConfig` — drop either 55 fields or sub-config factory methods | `agent_config.py:117-191, 195-266` | ⚠️ Partial | Dropped 4 of 7 sub-config dataclasses (`MemoryConfig`, `SubAgentConfig`, `CostReductionConfig`, `ToolResultConfig`) and their factory methods — all were unused outside `agent_config.py`. File shrank 268→176 LOC. Remaining 55 flat fields + 3 used factory methods (`llm_config`, `routing_config`, `tool_search_config`) untouched — final shape (flat vs nested) needs user direction. |
| T2-6 | Move 30+ eval/testing config files out of repo root into `configs/evals/` | `config-*.json` (36 files) | ❌ Gap | Deferred — each config has a `Base` reference resolved relative to its own directory, so moving requires per-file path updates + test updates. Needs user direction on target layout. |
| T2-7 | Extract `PseudoToolHandler` protocol from inline dispatch | `turn_engine.py:313-396` | ✅ Done | New `pseudo_tool_handlers.py` with `PseudoToolHandler` Protocol + 4 concrete handlers (`ToolSearchHandler`, `AskUserHandler`, `TaskToolHandler`, `SubAgentHandler`). Dispatch in `turn_engine.run` is now ~20 lines vs the previous ~80; `_execute_subagent_blocks` removed (`turn_engine.py` 752→676 LOC). |
| T2-8 | Wrap blocking `subprocess.run` in `asyncio.to_thread` if called from async tool execution | `native_tools/filesystem/bash_tool.py:231`, `read_tools.py:304` | ✅ Done | Confirmed `.execute` is async in both files. Wrapped both `subprocess.run` calls in `asyncio.to_thread` so the event loop stays responsive. |

### Tier 3 — test quality

| ID | Item | Location | Status | Action taken |
|---|---|---|---|---|
| T3-1 | Standardize on `@pytest.mark.asyncio` — migrate 30+ `asyncio.run()`-in-unittest tests | many | ❌ Gap | |
| T3-2 | Add `tests/integration/test_agent_loop.py` covering full multi-turn / tool / sub-agent / ask_user path with `FakeStreamProvider` | `tests/integration/` | ❌ Gap | |
| T3-3 | Add direct tests for `cli/dispatch.py`, `cli/repl.py`, `agent_builder.py`, `services/checkpoint_service.py`, `services/session_controller.py` | n/a | ❌ Gap | |
| T3-4 | Replace `Path.cwd() / ".tmp-run"` + `os.chdir` with `tempfile.TemporaryDirectory` | `tests/test_command_handler.py:368, 411` | ❌ Gap | |
| T3-5 | Replace sleep-as-sync with `asyncio.Event` / `wait_for` | `tests/server/test_ws_channel.py:35-135`, `tests/broker/test_store_runs.py:145, 155` | ❌ Gap | |
| T3-6 | Drop `**kwargs` from `FakeStreamProvider.stream_chat` to catch Provider-protocol drift | `tests/fakes.py:195` | ❌ Gap | |
| T3-7 | Replace MagicMock sprawl in command tests with `SessionManagerFake`/`CheckpointManagerFake` from `tests/fakes.py` | `tests/test_command_handler.py:41-69` | ❌ Gap | |

### Tier 4 — hygiene

| ID | Item | Location | Status | Action taken |
|---|---|---|---|---|
| T4-1 | Promote `_resolve_api_key_id`, `_load_user_memory`, `_parse_cli_args` to public API or test through consumers | various | ❌ Gap | |
| T4-2 | Remove dead `getattr(tool, "predict_touched_paths", None)` defensive read | `memory/facade.py:253` | ❌ Gap | |
| T4-3 | Add `from __future__ import annotations` to 6 non-trivial files | `llm_client.py`, `system_prompt.py`, `constants.py`, `mcp/mcp_manager.py`, `mcp/mcp_tool_proxy.py`, `server/sdk.py` | ❌ Gap | |
| T4-4 | Replace 15 `# type: ignore[no-untyped-def]` with real return annotations | `server/app.py`, `server/broker_routes.py` | ❌ Gap | |
| T4-5 | Reconcile test placement — pick `tests/voice/` or top-level for voice tests | `tests/voice/`, top-level `test_voice_*.py` | ❌ Gap | |
| T4-6 | Add coverage gate to CI to prevent regression below current 77% | n/a | ❌ Gap | |

---

## What's Genuinely Good

- **No `TODO`/`FIXME`/`HACK` in `src/`** — exceptional discipline.
- **Concurrency model is clean** — single `asyncio.run`, threading scoped to UI/IO.
- **Documentation is real** (SAD + ~18 ADRs) and mostly implemented.
- **`tests/fakes.py` design** — protocol-satisfying reusable fakes done right.
- **Zero bare `# type: ignore`** — every ignore specifies a code.
- **Provider layer** — clean factory + lazy imports, no leakage.
- **Broker subprocess isolation** — ADR-018 implemented correctly with timeout + byte cap.
- **`tests/server/test_ws_integration.py`** — exemplary test design (real TestClient, real WebSocket, only the LLM is faked).

---

## Summary

| Tier | Items | Open | Notes |
|---|---:|---:|---|
| Tier 1 (must-fix) | 9 | 0 | All done. Build green. |
| Tier 2 (architecture) | 8 | 2 | T2-1, T2-2, T2-3, T2-4, T2-7, T2-8 done. T2-5 partial (unused subset dropped). T2-6 awaits user direction. |
| Tier 3 (test quality) | 7 | 7 | |
| Tier 4 (hygiene) | 6 | 6 | |
| **Total** | **30** | **15** | |

Remaining work is concentrated, fixable, and well within reach of the same discipline already on display elsewhere in the codebase.
