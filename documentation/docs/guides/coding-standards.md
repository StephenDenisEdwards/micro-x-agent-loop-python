# Coding Standards

This document defines the coding standards for the micro-x-agent-loop-python project. All contributors — human and AI — must follow these standards. They are grounded in Python best practices and the SOLID, KISS, and DRY principles.

---

## 1. Python Best Practices

### 1.1 Code Style

- **Formatter/Linter:** Ruff (rules: E, F, W, I, B, UP), 120-character line length
- **Type Checker:** MyPy — all code must pass `mypy src/` with zero errors
- **Future Annotations:** Every module starts with `from __future__ import annotations`
- **Type Hints:** Required on all public functions, methods, and non-trivial variables
- **Modern Union Syntax:** Use `X | None` not `Optional[X]`, `dict[str, Any]` not `Dict[str, Any]`

### 1.2 Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `turn_engine.py` |
| Classes | `PascalCase` | `TurnEngine` |
| Functions/Methods | `snake_case` | `estimate_cost()` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_MAX_TOKENS` |
| Private members | Leading `_` | `_build_system_prompt()` |
| Type variables | `PascalCase` with `T` suffix | `MessageT` |

Avoid abbreviations unless universally understood (`id`, `url`, `db`). Prefer descriptive names — `pinned_target` over `pt`, `effective_model` over `em`.

### 1.3 Data Modelling

- **Dataclasses** for plain data containers — no hand-written `__init__` boilerplate
- **`frozen=True`** for immutable value objects (e.g., `DetectedSignal`, `ModeAnalysis`)
- **`field(default_factory=...)`** for mutable defaults — never use `[]` or `{}` as defaults
- **Enums / StrEnum** for fixed sets of values — not magic strings
- **Protocol classes** over ABCs for structural subtyping — prefer duck typing with type safety
- **`@runtime_checkable`** on Protocols that need `isinstance()` checks

### 1.4 Error Handling

- **Catch specific exceptions** — never bare `except:` or `except Exception:`
- **Don't silence errors** — `except SomeError: pass` requires a comment explaining why
- **Log on catch** — if you handle an exception, log it with context
- **Validate at boundaries** — trust internal code, validate user input and external API responses
- **EAFP over LBYL** — `try/except` is more Pythonic than pre-checking, but don't use it for control flow
- **Add context when re-raising** — use `raise NewError(...) from original` or log before `raise`

### 1.5 String Formatting

- **f-strings only** — no `.format()`, no `%` formatting
- Exception: `str.format()` is acceptable in template strings defined separately from their interpolation (e.g., LLM prompt templates with named placeholders)

### 1.6 File and Resource Handling

- **`pathlib.Path`** for all path manipulation — no `os.path`
- **Context managers (`with`)** for all resources — files, HTTP clients, locks, streams
- **`async with`** for async resources — `httpx.AsyncClient`, `aiofiles`, etc.

### 1.7 Imports

- **No wildcard imports** — `from x import *` is forbidden
- **`TYPE_CHECKING` guard** for imports used only in type annotations (prevents circular imports)
- **Ruff handles import sorting** — isort rules are enforced automatically

### 1.8 Functions and Methods

- **Keep functions small** — if a section needs a comment to explain it, extract it
- **Functions over classes** for stateless utilities — `cosine_similarity()` not `CosineSimilarityCalculator`
- **Generators (`yield`)** for large sequences — don't build lists you'll iterate once
- **Comprehensions** over `map`/`filter` for readability

### 1.9 Testing

- Tests in `tests/` using `unittest` (run via `pytest`)
- Test fakes in `tests/fakes.py` — `FakeStreamProvider`, `FakeTool`
- **Fakes over mocks** — they're more readable and catch interface drift
- **Test behaviour, not implementation** — tests shouldn't break on refactors
- **Arrange-Act-Assert** structure in every test
- Name test files `test_<module>.py`, test classes `Test<Feature>`, test methods `test_<behaviour>`

---

## 2. SOLID Principles

### 2.1 Single Responsibility Principle (SRP)

> A class should have only one reason to change.

- Each module should focus on **one concept** — `compaction.py` handles compaction, `embedding.py` handles vectors
- Classes should have a **single, well-defined responsibility** — not 9 concerns in one `__init__`
- If a constructor takes more than ~7 parameters, the class likely has too many responsibilities — consider extracting collaborators or using a config object
- If a method is longer than ~50 lines, look for extractable sub-methods

**Patterns to follow:**
- `CompactionStrategy` — single-method protocol, one concern
- `LogConsumer` — each implementation handles one output destination
- `ChannelAdapter` — each adapter handles one channel type

**Anti-patterns to avoid:**
- God classes with 900+ lines doing initialization, orchestration, and state management
- Constructors that create and configure 10+ subsystems inline

### 2.2 Open/Closed Principle (OCP)

> Software entities should be open for extension but closed for modification.

- Use **Protocol classes** as extension points — new providers, tools, channels, and strategies can be added without modifying existing code
- Use **factory functions** for object creation — centralise the `if/elif` in one place
- Prefer **configuration-driven behaviour** over code changes — routing policies, tool lists, and feature flags come from `config.json`
- Use **plugin/registry patterns** when the set of implementations grows beyond 3-4

**Patterns to follow:**
- `LLMProvider` Protocol + `create_provider()` factory
- `CompactionStrategy` — swap strategies via config without touching Agent
- `ChannelAdapter` — add new adapters without modifying dispatcher

### 2.3 Liskov Substitution Principle (LSP)

> Subtypes must be substitutable for their base types without altering correctness.

- All Protocol implementations must **honour the full contract** — same signatures, same semantics
- **Getters must not mutate state** — a method named `is_available()` should be pure
- **Null Object pattern** preferred over `None` checks — `NullMemoryFacade` and `NoneCompactionStrategy` can substitute freely without type narrowing
- When extending a class, **override behaviour, not contracts** — `DeepSeekProvider` and `OllamaProvider` correctly override only extraction/config methods

### 2.4 Interface Segregation Principle (ISP)

> Clients should not be forced to depend on interfaces they do not use.

- Keep Protocols **lean** — prefer 1-3 methods per protocol
- If a Protocol has 8+ methods, consider whether clients use all of them — split if not
- Use **separate config dataclasses** (`LLMConfig`, `MemoryConfig`, `RoutingConfig`) rather than one monolithic config — each component imports only what it needs
- When a Protocol mixes concerns (e.g., ingress + egress), split into focused sub-protocols

**Patterns to follow:**
- `CompactionStrategy` — 1 method
- `VoiceIngress` — 2 properties
- Sub-config dataclasses in `agent_config.py`

### 2.5 Dependency Inversion Principle (DIP)

> High-level modules should depend on abstractions, not concrete implementations.

- **Constructor injection** — pass dependencies in, don't create them inline
- High-level code (`Agent`, `TurnEngine`) should depend on **Protocols**, not concrete classes
- Use **`TYPE_CHECKING` guards** to reference types without circular imports — never fall back to `Any` to avoid import issues
- **Centralise object creation** in composition roots (`bootstrap.py`) or factory functions
- Avoid `Any` for typed dependencies — if a parameter has a known interface, use the Protocol type

**Patterns to follow:**
- `Agent` accepts `MemoryFacade` protocol, not `ActiveMemoryFacade`
- `TurnEngine` accepts `Tool` protocol, not `McpTool`
- `bootstrap.py` as the composition root that wires implementations to abstractions

---

## 3. KISS — Keep It Simple

> The simplest solution that works is the best solution.

### Guidelines

- **Don't build what you don't need** — no speculative abstractions, no unused extension points
- **Prefer functions over classes** for stateless operations
- **Prefer flat over nested** — avoid deep inheritance hierarchies; composition + Protocols work better
- **One way to do things** — if two subsystems solve the same problem, remove the older/unused one
- **Declarative over imperative** where possible — data-driven patterns beat hardcoded `if/elif` chains
- **Simple constructors** — if initialization requires 20+ lines of conditional logic, extract a builder or factory
- **Remove dead code** — unused routing systems, unimplemented features behind flags, and commented-out code all add cognitive load

### Complexity Smells

| Smell | Remedy |
|-------|--------|
| Multiple systems solving the same problem | Keep one, remove the rest |
| String concatenation building complex output | Use a builder or template |
| 50+ regex patterns defined inline | Move to a declarative pattern list |
| Constructor with 15+ parameters | Extract config object or collaborators |
| Feature flag checking repeated 6+ times | Registry or builder pattern |

---

## 4. DRY — Don't Repeat Yourself

> Every piece of knowledge must have a single, unambiguous, authoritative representation.

### Guidelines

- **Centralise constants** — all defaults in `constants.py`, all pricing in config, all prompts in `system_prompt.py`
- **Extract shared logic into functions** — if the same 5-line pattern appears in 3 places, extract it
- **Shared utilities for cross-cutting patterns** — `canonicalise_tools()` is a good example
- **Template-based prompt construction** — don't copy-paste prompt fragments across modules
- **Config expansion in one place** — a single pipeline for env var expansion, base inheritance, and ref resolution

### What DRY is NOT

- DRY does not mean "never write similar code" — **two functions with similar structure but different semantics are not duplication**
- DRY does not mean premature abstraction — **three similar lines are better than a premature helper** if the pattern hasn't stabilised
- DRY applies to **knowledge**, not syntax — if two code blocks express different decisions, they're not duplicates even if they look alike

### When to Extract

Extract when:
- The same logic appears in **3+ places** (Rule of Three)
- A change to the logic would require updating **multiple files**
- The duplicated code represents a **single piece of domain knowledge**

Don't extract when:
- Two pieces of code happen to look similar but serve different purposes
- The "shared" logic is 2-3 lines and trivially readable inline
- Extraction would create coupling between otherwise independent modules

---

## 5. Type Checking Rules

These rules are critical — violations block merges.

- **Annotate variables when the type isn't obvious** — especially when a variable holds multiple types across branches
- **Guard optional attributes before use** — if a field is `X | None`, check or assert before calling methods on it
- **Keep Protocol definitions in sync with implementations** — when you change a method signature, update the Protocol immediately
- **Annotate all functions** including inner functions, callbacks, and lambdas that mypy flags
- **Use `type: ignore` sparingly and with specific codes:**
  - `# type: ignore[arg-type]` — SDK calls accepting dicts at runtime but expecting typed params
  - `# type: ignore[import-untyped]` — third-party libs without stubs
  - `# type: ignore[unreachable]` — async code where state changes during `await`
- **Never use bare `# type: ignore`** — always specify the error code
- **For dynamic return values** (`resp.json()`, SQLite results), assign to a typed local: `result: list[dict[str, Any]] = resp.json()`

---

## 6. What NOT to Do

| Don't | Do Instead |
|-------|-----------|
| Create Python tool files | Tools are TypeScript MCP servers in separate repos |
| Use `git add -A` | Stage specific files |
| Skip pre-commit hooks (`--no-verify`) | Fix the issue the hook caught |
| Add dependencies without checking `pyproject.toml` | Verify the dep doesn't already exist or conflict |
| Use bare `# type: ignore` | Specify the error code |
| Use `os.path` for path operations | Use `pathlib.Path` |
| Use `Optional[X]` or `Union[X, Y]` | Use `X | None` or `X | Y` |
| Use `.format()` or `%` for string formatting | Use f-strings |
| Catch bare `Exception` without logging | Catch specific exceptions, log with context |
| Create abstractions for one-time operations | Write the code inline |
| Add speculative features or extension points | Build what's needed now |

---

## Appendix A: Project Conformity Analysis (2026-04-01)

This appendix assesses the current codebase against the standards defined above. For the full detailed audit with line-level references, see [ISSUE-004](../issues/ISSUE-004-solid-dry-kiss-compliance-2026-04-01.md).

### Scorecard

| Principle | Grade | Summary |
|-----------|-------|---------|
| **SRP** | C+ | Strong module boundaries, but `Agent` (915 lines), `TurnEngine` (719 lines), and `__main__.py` (544 lines) are god classes with too many responsibilities |
| **OCP** | A- | Excellent Protocol-based extension points; provider factory requires code changes for new providers |
| **LSP** | B+ | All Protocol implementations honour contracts; `ProviderStatus.is_available()` has a side-effect smell |
| **ISP** | B | Good sub-config segregation; `MemoryFacade` (9 methods) and `TurnEvents` (8+ methods) are broader than necessary |
| **DIP** | A- | Strong injection via constructor args and Protocols; some `Any` types used to work around circular imports |
| **DRY** | C | Constants centralised well; message format conversion duplicated across 3 providers (~160 lines); system prompt built by 6+ repeated conditional blocks; config expansion pipeline repeated 3x |
| **KISS** | C- | Three routing systems coexist (only one active); four separate message format converters; mode analysis subsystem is unimplemented but still present |
| **Type Hints** | B+ | Comprehensive coverage with modern syntax; some `Any` escape hatches in `TurnEngine` and `agent_config.py` where Protocol types should be used |
| **Dataclasses** | A | Consistent use with `frozen=True` for value objects and `default_factory` for mutables |
| **Protocols/Enums** | A | 10+ well-designed Protocols; proper StrEnum usage throughout |
| **Error Handling** | B- | Mostly specific catches; some broad `except Exception:` in `embedding.py`, `agent_channel.py`, `provider_pool.py` with no logging |
| **Naming** | A- | Consistent PEP 8 naming; descriptive identifiers; one `.format()` outlier in `semantic_classifier.py` |
| **Pathlib** | A | Zero `os.path` usage; `pathlib.Path` throughout |
| **Context Managers** | A | Proper `with`/`async with` for all resources |

### What Works Well

These patterns are exemplary and should be preserved:

- **Protocol-based provider architecture** — adding a new LLM provider requires one class + one factory line
- **Tool Protocol + MCP proxying** — tools added via config, not code changes
- **AgentChannel Protocol** — clean separation of Terminal, Buffered, and Broker channels
- **CompactionStrategy Protocol** — minimal single-method interface, Null Object pattern
- **Null Object pattern** — `NullMemoryFacade`, `NoneCompactionStrategy` eliminate null checks
- **Centralised constants** — `constants.py` as single source of truth for defaults
- **Dataclass discipline** — frozen value objects, factory defaults, sub-config extraction
- **Modern Python idioms** — f-strings, pathlib, `X | None` syntax, `from __future__ import annotations`

### Top Issues Requiring Attention

| Priority | Issue | Principle | Impact |
|----------|-------|-----------|--------|
| 1 | Three routing systems coexist; only semantic routing is active | KISS | ~1000 lines of dead/redundant code |
| 2 | `Agent.__init__()` handles 9+ responsibilities in 174 lines | SRP | Hard to test, hard to modify |
| 3 | Message format conversion duplicated across 3 providers | DRY | ~160 lines duplicated |
| 4 | System prompt built via 6+ repeated conditional string appends | DRY, SRP | Fragile, hard to test |
| 5 | `TurnEngine` constructor takes 17+ parameters | SRP, KISS | Signals mixed concerns |
| 6 | `Any` types used where Protocol types should be | DIP | Lost static safety |
| 7 | Broad `except Exception:` without logging in 3+ files | Error Handling | Silent failures |

### Remediation Roadmap

See [ISSUE-004](../issues/ISSUE-004-solid-dry-kiss-compliance-2026-04-01.md) for the full refactoring priority list. The recommended order:

1. Remove dead routing systems (per-turn classifier + mode analysis)
2. Extract `MessageConverter` Protocol for provider format conversion
3. Extract `SystemPromptBuilder` from `agent.py`
4. Extract `RoutingEngine` from `TurnEngine`
5. Centralise provider creation in a `ProviderFactory`
6. Replace `Any` escape hatches with proper Protocol types
7. Add specific exception handling where broad catches exist
