# Codebase Review — 2026-06-05 follow-ups (v0.2.1) and forward roadmap

**Reviewed:** 2026-06-05 (initial), 2026-06-05 (second pass at v0.2.0), 2026-06-05 (third pass at v0.2.1)
**Companion to:** [codebase-review-2026-06-05.md](codebase-review-2026-06-05.md) — that doc tracks the original 30 items.
**Scope of this doc:** What happened *after* the original review closed at v0.2.0 — the second-pass re-audit, the v0.2.1 cleanup release, and the forward roadmap (v0.2.2 hygiene, v0.3.0 architecture) surfaced by the audits.
**Status key:** `✅ Done` · `⚠️ Partial` · `🔲 Planned` · `❌ Open`

---

## Release timeline

| Release | What it captured | Tag |
|---|---|---|
| v0.1.0 baseline | Pre-review state (untagged) | — |
| **v0.2.0** | All 30 review items addressed | `v0.2.0` (annotated) |
| **v0.2.1** | 8 follow-up items from the second-pass re-audit | `v0.2.1` (annotated) |

Both tags are annotated and carry the full release notes (`git show v0.2.0`, `git show v0.2.1`).

---

## Second-pass re-audit (against v0.2.0)

The first review closed with a self-declared "30/30 done." A second, independent pass — four parallel agents auditing architecture, standards/types, coverage, and test quality — verified the original 30 items and surfaced **8 fresh follow-up observations** that weren't in scope of the original review. Those 8 became v0.2.1.

### Original 30 — all verified done

The second-pass agents confirmed every item that the original review marked done was in fact done in the current code, with file:line citations. Notable:

- `agent.py` 1,219 → 872 LOC verified (with the 9 in-function imports collapsed to 3 legitimate ones, e.g. `agent_builder` deliberate circular-break at `:49`).
- `commands/command_handler.py` 1,062 → 189 LOC verified — drops out of the top-10 file-size list entirely.
- `AgentChannel` Protocol verified to include `begin_streaming` / `end_streaming` (`agent_channel.py:122-128`) with all 5 implementations matching.
- `PseudoToolHandler` protocol verified — dispatch in `turn_engine.py:346-357` walks the registered list.
- ADR-024 violation gone (`git ls-files mcp_servers/ts/packages/web/dist` returns 0).
- 56 test files migrated to `IsolatedAsyncioTestCase` — only 1 `asyncio.run(` left across all tests, in `tests/evals/harness.py` (a harness, not a unit test).
- Config files reorganised: 36 → 3 at root.

### 8 follow-up observations → v0.2.1

These were *out of scope* of the original 30 — fresh observations that the second-pass agents surfaced.

| ID | Item | Action | Status |
|---|---|---|---|
| F-A | `from __future__ import annotations` sweep — flagged as missing in 18 files | Verified by full-file (not `head -10`) grep — **all 142 source files already have it**. The second-pass agent's grep was fooled by long docstrings. | ✅ Non-issue |
| F-B | 9 tests still import private `_foo` symbols | Promoted to public: `on_retry`, `build_tool_use_id_map`, `is_retryable_gemini_error`, `SUBAGENT_DIRECTIVE`, `sort_schema`, `get_context_window`, `parse_json_object` (× 2 — module fn + method), `truncate_output`, `format_for_summarization`. All call sites updated. | ✅ Done |
| F-C | 3 surviving `# type: ignore[assignment]` ignores in `server/app.py:197,211,215` | Replaced with `TYPE_CHECKING` imports + explicit narrowed declarations (`sched: Scheduler \| None = _state.get(...)`). Zero ignores remain on `server/app.py`. | ✅ Done |
| F-D | Stale config ref in `tests/evals/filesystem-navigation/README.md:64` | Updated to the new `configs/evals/config-eval-haiku.json` path. | ✅ Done |
| F-E | 5 wall-clock sleeps in tests | Removed 3 (spinner-idempotency tests), made one deterministic via `os.utime()` (mtime-ordering test wouldn't have worked anyway on 1s-resolution filesystems), shortened one from 2.0s → 0.5s (`ws_integration` mid-turn ping test). | ✅ Done |
| F-F | Integration test reaches into `agent._messages` / `agent._turn_number` at 7 sites — fragile under refactor | Added public `agent.history` and `agent.turn_number` properties on `Agent`. Integration tests rewritten to use them. | ✅ Done |
| F-G | Integration test doesn't exercise `spawn_subagent` despite the brief listing it | Added `SpawnSubagentPseudoToolTests` end-to-end scenario in `tests/integration/test_agent_loop.py`. Wires `sub_agents_enabled` + compact routing policy to trigger `SubAgentRunner` construction in `agent_builder`, patches `SubAgentRunner.run` with a canned `SubAgentResult`, asserts the result lands as a `tool_result` block and the loop continues. | ✅ Done |
| F-H | 10 `Any` fields on `AgentComponents` (`agent_builder.py:38-85`) | Typed with real Protocols via `TYPE_CHECKING` imports — `LLMProvider`, `AgentChannel`, `CompactionStrategy`, `LLMCompactor`, `ProviderPool`, `RoutingFeedbackStore`, `SemanticClassifierFn`, `RoutingFeedbackFn`. Zero `Any` on the dataclass; 1 leftover in a helper signature (acceptable). | ✅ Done |

**8/8 items closed in v0.2.1.**

---

## Third-pass verification (against v0.2.1)

A third pass after the v0.2.1 commit verified every F-A through F-H landed correctly with file:line evidence:

- `agent.history` / `agent.turn_number` confirmed at `agent.py:817-829`.
- `AgentComponents` confirmed zero `Any` fields on the dataclass (`agent_builder.py:42-95`).
- `server/app.py` confirmed zero `# type: ignore` (was 3 at v0.2.0).
- All 9 promoted symbols verified present at the public name; underscored variants gone.

### Pleasant surprises uncovered by the third pass

1. **`TurnEvents` Protocol was already trimmed.** The second-pass review flagged 17 methods. Current count is **14** (`turn_events.py:12-86`). Trimmed organically.
2. **`from __future__ import annotations` actually missing in zero src files.** The second-pass false positive was diagnosed in F-A.
3. **Test count went up by 15, not just 1.** The subagent test added one; new test class structure surfaced parametrised cases.

### Cumulative metrics — v0.1.0 → v0.2.0 → v0.2.1

| Metric | v0.1.0 (start) | v0.2.0 | v0.2.1 | Δ since start |
|---|---:|---:|---:|---|
| Ruff violations | 12 | 0 | 0 | -12 |
| Mypy errors | 2 | 0 | 0 | -2 |
| Tests passing | 1,834 | 1,886 | 1,887 | +53 |
| Tests failing | 5 | 0 | 0 | -5 |
| `# type: ignore` (src) | 32 | 22 | 19 | -13 |
| Bare `# type: ignore` | 0 | 0 | 0 | clean |
| `Any` on `AgentComponents` | 10 | 10 | 0 | -10 |
| `# type: ignore` in `server/app.py` | 15 | 3 | 0 | -15 |
| Root `config-*.json` | 36 | 3 | 3 | -33 |
| `asyncio.run(` in tests | 30+ files | 1 site | 1 site | (eval harness) |
| Largest src file | `agent.py` 1,219 | `tui/app.py` 883 | `tui/app.py` 883 | -336 |
| `agent.py` LOC | 1,219 | 872 | 886 | -333 |
| `command_handler.py` LOC | 1,062 | 189 | 189 | -873 |
| Coverage | 77% | 76% | 76% | -1pp |
| CI coverage gate | none | 75% | 75% | enforced |

---

## Forward roadmap

The third-pass audit produced three prioritised lists of remaining work, sorted by effort/value. None are regressions; all are forward-looking polish.

### v0.2.2 — hygiene (Standards Agent's "Top 5 fast follower")

| Item | File | Effort |
|---|---|---|
| Tighten `routing_strategy.py` `Any` annotations (7 `Any \| None` params point to concrete in-tree classes) | `routing_strategy.py` | Small |
| Widen CI mypy gate from 5 paths to full `src/` | `.github/workflows/python-tests.yml` | Trivial |
| Raise `--cov-fail-under` from 75 → 78 (lock in headroom; currently 1.1 pp buffer) | `.github/workflows/python-tests.yml` | Trivial |
| Replace `ws: Any` in `server/sdk.py` with `WebSocketClientProtocol` from `websockets.client` | `server/sdk.py` | Small |
| Add a `ruff format --check` gate for `mcp_servers/ts/` (Python side is fully gated; TS side has no parallel) | CI workflow | Small |

### v0.2.x — test quality (Test-Quality Agent's "Top 3")

| Item | Notes |
|---|---|
| Mock-spec discipline — 293 unspecced `MagicMock()` + 75 unspecced `AsyncMock()` vs 4 specced. Protocol drift won't surface as test failures. | Large mechanical sweep; could be incremental — fix worst offenders first |
| 4 removable real-time `asyncio.sleep` waits (0.12s–0.5s) in `test_voice_runtime.py:71`, `memory/test_event_sink.py:25`, `memory/test_stress_and_retention.py:251`, `server/test_ws_integration.py:219` | Replace with `asyncio.Event` barriers or fake clocks |
| Inline lazy imports in `test_cost_reconciliation.py` (×12) and `test_gemini_provider.py` (×8) — hints at module-level import fragility that should be diagnosed in production code, not papered over | Investigation, not just refactor |

### v0.3.0 — architecture (Architecture Agent's "Top 5 v0.3 candidates")

| Item | File:line evidence | Why it matters |
|---|---|---|
| Collapse `AgentConfig` flat fields into sub-configs **or** drop the factories | `agent_config.py:68-142` (60+ fields) + `:146-165` (3 factories) | Two sources of truth for the same settings; the worst-of-both-worlds pattern. |
| Split `TurnEngine` (676 LOC, 14-method TurnEvents) | `turn_engine.py`, `turn_events.py:12-86` | Extract a `ToolDispatcher` (regular + pseudo); let TurnEvents shrink to actual lifecycle hooks. |
| Replace positional pseudo-handler list with name-keyed registry; detect collisions at construction | `turn_engine.py:111-121` (build), `:350-353` (dispatch) | First-match-wins dispatch can silently shadow handlers if a future handler claims an overlapping name. |
| Make `Agent.history` return an immutable view (`MappingProxyType` or `tuple`) | `agent.py:817-824` | Currently returns a live `list[dict]`; the docstring warns but doesn't enforce. Cheap fix. |
| Apply v0.2.1's `TYPE_CHECKING` pattern to `agent_config.py:135` (`channel: Any` with "circular import" comment) | `agent_config.py:135` | The circular-import excuse is fixable; apply the pattern consistently. |

### Coverage gaps (Coverage Agent's "Top 3")

These are the modules where a bug has the highest user-visible blast radius and where coverage could plausibly be added without huge effort:

1. **`cli/repl.py`** (179 LOC, 0 tests) — primary user-facing surface; any regression in slash-dispatch, Ctrl-C, or stdin handling breaks every interactive session silently.
2. **`__main__.py`** (135 LOC, only `parse_cli_args` smoke-tested) — owns CLI flag dispatch (`--run`, `--broker`, `--server`, `--tui`). Broken flag → every entry path broken.
3. **`bootstrap.py`** (309 LOC, 4 tests) — wires memory, MCP servers, event sinks. Regression here corrupts every session silently.

`tui/app.py` (883 LOC, 0%) is the largest single uncovered file but has well-documented test-effort hostility (Textual TUI is hard to unit-test). Worth coverage-gating but lower priority than the entry points above.

---

## Coverage-floor math

The third-pass coverage agent did the arithmetic:

- Current: **76%** of 12,451 statements → 9,463 covered.
- Add 200 new uncovered LOC: **9,463 / 12,651 = 74.8%** → **fails the 75% gate**.
- Headroom is ~138 LOC — roughly one medium PR of new src code without any tests trips the gate.

Two options for v0.2.2:
1. **Raise floor to 78%** to lock in headroom (preferred — matches actual quality).
2. **Add per-PR coverage delta checks** rather than absolute floor (better signal but more CI complexity).

---

## How to read this doc

- **Done** items (F-A through F-H) shipped in v0.2.1. Their commits are at `da5298e..ffe6f6e` on master.
- **Open** items (v0.2.2 hygiene, v0.2.x test quality, v0.3.0 architecture, coverage gaps) are not yet tracked as commitments — they're a prioritised backlog from three independent audits. Pick from the top of each list when bandwidth allows.
- The original 30-item review at [codebase-review-2026-06-05.md](codebase-review-2026-06-05.md) is the historical record; this doc is the "what's next" companion.

---

## Pointers

- Tag annotations carry full release notes: `git show v0.2.0`, `git show v0.2.1`.
- Build state at v0.2.1: ruff clean · mypy clean · **1,887 tests pass** / 14 skipped / 0 failing · **76% coverage** · 75% CI gate.
- ADR-024 CI grep gate active in `.github/workflows/python-tests.yml`.
- Coverage CI gate active in same workflow file.
