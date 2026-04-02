# ISSUE-004: SOLID, DRY, and KISS Compliance Gaps

## Date

2026-04-01

## Status

**In Progress** — Sections 1 (SRP), 3.1 (KISS), 4.1 (LSP) complete. DRY §2.1 addressed (shared helper). Remaining: §2.2, §2.4, §3.2–3.3, §4.2–4.3.

## Summary

An audit of the codebase against SOLID, DRY, and KISS principles reveals strong Protocol-based extensibility (OCP, DIP) but significant issues with god classes (SRP), duplicated format conversion logic (DRY), and dead/redundant routing subsystems (KISS). This issue documents the findings and proposes targeted refactorings.

## Overall Assessment

| Principle | Grade | Key Issue |
|-----------|-------|-----------|
| Single Responsibility | C+ | God classes: `agent.py`, `turn_engine.py`, `app_config.py` |
| Open/Closed | A- | Protocol design is excellent |
| Liskov Substitution | B+ | Minor state-mutation smell in `ProviderStatus` |
| Interface Segregation | B | `AgentConfig` bloated (50+ fields) |
| Dependency Inversion | A- | Good injection; provider creation scattered |
| DRY | C | Message conversion, config loading, prompt building duplicated |
| KISS | C- | 3 routing systems, 4 format converters, complex session mgmt |

---

## 1. Single Responsibility Violations

### 1.1 `agent.py` (915 lines) — ✅ Complete

Extracted `AgentBuilder` (`agent_builder.py`) for subsystem construction and `SystemPromptBuilder` (`system_prompt_builder.py`) for directive consolidation. Agent reduced to 738 lines.

### 1.2 `turn_engine.py` (719 lines) — ✅ Complete

Extracted `RoutingStrategy` (`routing_strategy.py`) for routing decisions (pin continuation, semantic, legacy, per-policy overrides). TurnEngine reduced to 592 lines.

### 1.3 `agent_config.py` — ✅ Complete

Added 7 sub-config dataclasses (`LLMConfig`, `MemoryConfig`, `RoutingConfig`, `ToolSearchConfig`, etc.) with factory methods.

### 1.4 `__main__.py` (544 lines) — ✅ Complete

Split into `cli/` package: `dispatch.py`, `repl.py`, `esc_watcher.py`. `__main__.py` reduced to 130 lines.

### 1.5 `agent_channel.py` (581 lines) — ✅ Complete

Extracted `terminal_renderer.py` and `terminal_prompter.py`. `agent_channel.py` reduced to 384 lines.

---

## 2. DRY Violations

### 2.1 Message/Tool Format Conversion (~160 lines duplicated)

`_to_openai_messages()` (82 lines) and `_to_gemini_contents()` (68 lines) perform the same structural transformation — extract role/content, handle assistant messages with tool_use blocks, handle user messages with tool_result blocks — with different output shapes. Tool conversion functions (`_to_openai_tools`, `_to_gemini_tools`) duplicate the same pattern.

**Recommendation:** Extract a `MessageConverter` Protocol with provider-specific implementations.

### 2.2 Config Expansion Pipeline (3x repetition)

The sequence `_resolve_config_with_base()` → `_expand_config_refs()` → `_expand_env_vars()` is repeated in 3 code paths within `app_config.py`.

**Recommendation:** Extract `_apply_expansions(data: dict) -> dict` function.

### 2.3 System Prompt Directive Appending (6+ repetitions)

The same pattern in `agent.py` repeats 6+ times:

```python
if <feature_flag>:
    from micro_x_agent_loop.system_prompt import _SOME_DIRECTIVE
    self._system_prompt += _SOME_DIRECTIVE
```

**Recommendation:** Registry-based approach or `SystemPromptBuilder` that accepts feature flags and constructs the prompt in one pass.

### 2.4 Routing Target Resolution (2x duplication)

Similar routing logic appears in both `turn_engine.py` (runtime resolution) and `agent.py` (initialization). Both check routing policies, resolve provider availability, and fall back to the main model.

---

## 3. KISS Violations

### 3.1 Redundant Per-Turn Routing System — ✅ Complete

Per-turn routing (`turn_classifier.py`) removed. Mode analysis retained for future compiled-mode execution. Saved ~500 lines. See commit `e26c031`.

### 3.2 Four Separate Message Format Converters

Each provider has its own message/tool conversion functions instead of one abstraction with provider-specific backends:

- `openai_provider.py` — OpenAI format
- `gemini_provider.py` — Gemini format
- `anthropic_provider.py` — internal/native format
- `ollama_provider.py` — inherits OpenAI format

**Recommendation:** Single `FormatConverter` abstraction with pluggable provider backends.

### 3.3 Complex Session Management

Four strategies (resume/continue/new/fork) spread across `bootstrap.py` with multiple conditional branches.

**Recommendation:** Single `load_or_create_session(identifier, strategy)` method where strategy is an enum.

### 3.4 System Prompt Built via Manual String Concatenation

`agent.py` checks 8+ feature flags and appends directive strings one at a time. Hard to test, understand, or compose.

**Recommendation:** `SystemPromptBuilder` with a declarative API.

---

## 4. Minor Issues

### 4.1 LSP — `ProviderStatus.is_available()` Mutates State — ✅ Complete

Separated into pure `is_available()` (no side effects) and `check_and_reset_availability()` (resets cooldown state). `ProviderPool.resolve_target()` uses `_check_and_reset()` before dispatch; `is_available()` remains pure for queries. GitHub issue #9.

### 4.2 ISP — `LLMProvider` Protocol Could Be Narrower

`LLMProvider` bundles `stream_chat`, `create_message`, and `convert_tools`. Not all providers need all three — `create_message` is only used for compaction.

**Fix:** Split into `LLMProvider` (stream_chat, family) and optional `LLMCompactor` (create_message).

### 4.3 DIP — Provider Creation Scattered

Provider instances are created directly in `agent.py`, `bootstrap.py`, `sub_agent.py`, and others. A centralized `ProviderFactory` would improve this.

---

## What Works Well

These patterns should be preserved:

- **Protocol-based provider architecture** — Adding a new LLM provider requires one class + one factory line
- **Tool Protocol + MCP proxying** — Tools added via config, not code changes
- **AgentChannel Protocol** — Clean separation of Terminal, Buffered, and Broker channels
- **CompactionStrategy Protocol** — Minimal single-method interface
- **Dependency injection throughout** — Agent/TurnEngine receive all dependencies as constructor args

---

## Proposed Refactoring Priority

| Priority | Refactoring | Impact | Status |
|----------|-------------|--------|--------|
| 1 | Remove per-turn routing system | KISS §3.1 | ✅ Done (commit e26c031) |
| 2 | Extract shared `normalize_tool_content` | DRY §2.1 | ✅ Done — shared helper extracted. Full Protocol deemed over-engineering (conversions are necessarily provider-specific). GH #5 |
| 3 | Extract `SystemPromptBuilder` | DRY §2.3, SRP | ✅ Done (commit 9a4a41b) |
| 4 | Extract `RoutingEngine` from TurnEngine | SRP §1.2 | ✅ Done as `RoutingStrategy` (commit 9a4a41b) |
| 5 | Extract `ProviderFactory` | DIP §4.3 | Open (GH #6) |
| 6 | Split `AgentConfig` into sub-configs | ISP §1.3 | ✅ Done (commit 9a4a41b) |
| 7 | Extract `__main__.py` dispatch modules | SRP §1.4 | ✅ Done as `cli/` package (commit 9a4a41b) |
| — | Fix `ProviderStatus.is_available()` mutation | LSP §4.1 | ✅ Done. GH #9 |

Each remaining refactoring is independent and can be done incrementally.
