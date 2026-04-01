# ISSUE-004: SOLID, DRY, and KISS Compliance Gaps

## Date

2026-04-01

## Status

**Open** — Analysis complete, no refactoring started.

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

### 1.1 `agent.py` (915 lines) — Critical

The `Agent.__init__()` handles 9+ distinct responsibilities:

- Provider creation
- Tool map building
- Tool search initialization
- Sub-agent setup
- Memory facade setup
- Voice runtime initialization
- Command router creation
- Mode analysis setup
- Semantic routing setup

**Impact:** Massive constructor makes testing hard. Changes to any subsystem require understanding all dependencies.

**Recommendation:** Extract factory methods or use composition with specialized builders.

### 1.2 `turn_engine.py` (719 lines) — Significant

Constructor takes 17+ parameters covering LLM config, system prompt management, tool management, summarization, routing, formatting, and sub-agents. The `run()` method orchestrates all of these in a single method.

**Recommendation:** Extract `RoutingEngine`, `ToolExecutor`, and `CostTracker` classes.

### 1.3 `app_config.py` — Moderate

`AppConfig` dataclass has 55+ fields mixing LLM selection, memory, compaction, tool search, routing, broker, and formatting config. Config loading repeats the same expansion pipeline in 3 places.

**Recommendation:** Split into `LLMConfig`, `MemoryConfig`, `RoutingConfig`, `ToolSearchConfig` sub-configs.

### 1.4 `__main__.py` (544 lines) — Moderate

Single file handles REPL, `--run` autonomous mode, `--broker` daemon management, `--job` scheduler, and `--server` API dispatch.

**Recommendation:** Extract `REPLRunner`, `BrokerManager`, `JobManager`, `ServerManager` modules.

### 1.5 `agent_channel.py` (581 lines) — Moderate

`TerminalChannel` mixes live markdown rendering (rich.Live), spinner animation, interactive prompts (questionary), and output buffering.

**Recommendation:** Extract `MarkdownRenderer`, `ToolSpinner`, `InteractivePrompt` classes.

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

### 3.1 Three Redundant Routing Systems (~2000 lines)

Three routing systems exist simultaneously but are mutually exclusive:

1. **Per-turn routing** (`turn_classifier.py`) — Legacy binary classifier (cheap vs. main model)
2. **Semantic routing** (`semantic_classifier.py` + `task_taxonomy.py`) — 9 task types mapped to routing policies
3. **Mode analysis** (`mode_selector.py`) — Stage 1 pattern matching + Stage 2 LLM classification, currently diagnostic only / unimplemented

Only semantic routing is actively used.

**Recommendation:** Remove per-turn routing (legacy) and mode analysis (unimplemented). Saves ~1000 lines.

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

### 4.1 LSP — `ProviderStatus.is_available()` Mutates State

In `provider_pool.py`, calling `is_available()` may reset `self.available` if the cooldown has expired. Getters should not have side effects.

**Fix:** Separate into pure `is_available()` and `check_and_reset_availability()`.

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

| Priority | Refactoring | Impact | Estimated Reduction |
|----------|-------------|--------|---------------------|
| 1 | Remove dead routing systems (per-turn + mode analysis) | KISS | ~1000 lines |
| 2 | Extract `MessageConverter` Protocol | DRY | ~150 lines deduped |
| 3 | Extract `SystemPromptBuilder` | DRY, SRP | ~80 lines from agent.py |
| 4 | Extract `RoutingEngine` from TurnEngine | SRP | ~200 lines from turn_engine.py |
| 5 | Extract `ProviderFactory` | DIP | Centralizes 5 creation sites |
| 6 | Split `AgentConfig` into sub-configs | ISP | Clearer interfaces |
| 7 | Extract `__main__.py` dispatch modules | SRP | ~300 lines from __main__.py |

Each refactoring is independent and can be done incrementally.
