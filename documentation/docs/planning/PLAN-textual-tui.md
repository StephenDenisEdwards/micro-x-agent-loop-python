# Plan: Textual TUI for CLI

**Status:** Completed
**Date:** 2026-04-02
**ADR:** [ADR-022](../architecture/decisions/ADR-022-textual-tui-for-cli.md)
**Goal:** Add an opt-in Textual-based TUI (`--tui` flag) that provides a richer interactive experience — scrollable chat, tool visibility panel, modal ask_user, session sidebar — while keeping the existing REPL as the default.

---

## 1. Problem

The current CLI is built from three independent libraries (prompt_toolkit, rich, questionary) that fight for terminal control. Output re-renders destructively via `rich.Live`, tool execution is opaque (single inline spinner), `ask_user` tears down the renderer to hand off to questionary, and the entire UI is a single column of text with no room for status panels or session navigation.

See [ADR-022](../architecture/decisions/ADR-022-textual-tui-for-cli.md) for the full context and wireframes.

---

## 2. Approach

Implement a `TextualApp` (subclass of `textual.App`) and a `TextualChannel` (implementing the existing `AgentChannel` protocol). Launch via `--tui` flag. The agent core, turn engine, providers, tools, memory, config, and all other modes (`--run`, `--server`, `--broker`) are untouched.

Textual is from the same team as Rich (already a dependency) and uses Rich internally for rendering.

---

## 3. Phases

### Phase 1 — Core Chat (MVP)

Functional parity with the current REPL: type a message, see the streamed response, repeat.

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 1.1 | Add `textual>=1.0` as optional dependency | `pyproject.toml` | Trivial |
| 1.2 | Create `tui/` package scaffold | `src/micro_x_agent_loop/tui/__init__.py` | Trivial |
| 1.3 | Implement `TextualChannel` (`AgentChannel` protocol) | `tui/channel.py` | Medium |
| 1.4 | Implement `ChatLog` widget — scrollable conversation with markdown rendering | `tui/widgets/chat_log.py` | Medium |
| 1.5 | Implement `InputArea` widget — multi-line input with Enter/Shift+Enter bindings | `tui/widgets/input_area.py` | Medium |
| 1.6 | Implement `StatusBar` widget — turn count, cost, tokens, context size | `tui/widgets/status_bar.py` | Small |
| 1.7 | Implement `TextualApp` — composes ChatLog + InputArea + StatusBar, wires agent | `tui/app.py` | Large |
| 1.8 | Add `--tui` CLI flag, wire to `TextualApp` launch | `__main__.py`, `cli/dispatch.py` | Small |
| 1.9 | Add TCSS stylesheet for layout and theming | `tui/styles/app.tcss` | Small |
| 1.10 | Handle Escape key for turn cancellation (replace `EscWatcher`) | `tui/app.py` | Small |
| 1.11 | Handle `/` slash commands via InputArea (delegate to existing `CommandRouter`) | `tui/app.py` | Small |
| 1.12 | Thinking spinner in ChatLog while waiting for first token | `tui/widgets/chat_log.py` | Small |
| 1.13 | Startup banner and config info display | `tui/app.py` | Trivial |
| 1.14 | Tests — `TextualChannel` unit tests, `TextualApp` pilot tests | `tests/test_textual_channel.py`, `tests/test_textual_app.py` | Medium |

**Exit criteria:** User can launch `--tui`, have a multi-turn conversation with streamed markdown responses, see cost/token status, cancel with Escape, run slash commands, and exit cleanly.

### Phase 2 — Tool Panel

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 2.1 | Implement `ToolPanel` widget — list of tool executions with status/timing | `tui/widgets/tool_panel.py` | Medium |
| 2.2 | Wire `emit_tool_started` / `emit_tool_completed` to ToolPanel | `tui/channel.py` | Small |
| 2.3 | Add Ctrl+T toggle to show/hide tool panel | `tui/app.py` | Small |
| 2.4 | TCSS for tool panel layout (right sidebar, collapsible) | `tui/styles/app.tcss` | Small |
| 2.5 | Tests — tool panel rendering and state transitions | `tests/test_textual_app.py` | Small |

**Exit criteria:** Tool calls appear in a right sidebar with name, duration, and success/error status. Panel toggles on/off without disrupting the chat.

### Phase 3 — ask_user Modal

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 3.1 | Implement `AskUserModal` screen — question text, radio options, free-text input, submit | `tui/screens/ask_user_modal.py` | Medium |
| 3.2 | Wire `TextualChannel.ask_user()` to push modal, await result via `asyncio.Future` | `tui/channel.py` | Medium |
| 3.3 | TCSS for modal styling (centered overlay, dimmed background) | `tui/styles/app.tcss` | Small |
| 3.4 | Tests — modal lifecycle, option selection, free-text fallback, cancel | `tests/test_textual_app.py` | Medium |

**Exit criteria:** When the LLM calls `ask_user`, a centered modal appears with the question and options. User can select an option, type a free-form answer, or cancel. Result flows back to the agent without disrupting chat state.

### Phase 4 — Session Sidebar

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 4.1 | Implement `SessionSidebar` widget — list sessions, highlight active, show name/date | `tui/widgets/session_sidebar.py` | Medium |
| 4.2 | Click-to-switch session (delegates to existing `SessionController`) | `tui/widgets/session_sidebar.py` | Medium |
| 4.3 | New/Fork session buttons | `tui/widgets/session_sidebar.py` | Small |
| 4.4 | Add Ctrl+S toggle to show/hide session sidebar | `tui/app.py` | Small |
| 4.5 | TCSS for session sidebar layout (left sidebar, collapsible) | `tui/styles/app.tcss` | Small |
| 4.6 | Tests — session list rendering, switch, new, fork | `tests/test_textual_app.py` | Medium |

**Exit criteria:** Sessions appear in a left sidebar. Clicking a session switches to it (loads history into ChatLog). New and Fork buttons work. Sidebar toggles without disrupting chat.

### Phase 5 — Polish

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 5.1 | Integrate Textual command palette for slash commands | `tui/app.py` | Medium |
| 5.2 | Responsive layout — gracefully degrade for narrow terminals (hide sidebars) | `tui/styles/app.tcss` | Small |
| 5.3 | Mode analysis prompt (PROMPT/COMPILED choice) as inline widget or modal | `tui/app.py` | Small |
| 5.4 | Theming support — light/dark, configurable via config key | `tui/styles/` | Small |
| 5.5 | Inline notification toasts for budget warnings, system messages | `tui/app.py` | Small |

**Exit criteria:** Slash commands discoverable via Ctrl+P palette. Layout adapts to terminal size. Theming works.

---

## 4. Architecture

```
__main__.py
  ├── --tui flag → tui/app.py → TextualApp.run()
  └── (default)  → cli/repl.py → run_repl()  (unchanged)

tui/
  ├── __init__.py
  ├── app.py              TextualApp(textual.App) — composes widgets, wires agent
  ├── channel.py          TextualChannel(AgentChannel) — bridges agent ↔ Textual
  ├── widgets/
  │   ├── chat_log.py     Scrollable conversation with markdown rendering
  │   ├── input_area.py   Multi-line text input with key bindings
  │   ├── status_bar.py   Cost, tokens, session info
  │   ├── tool_panel.py   Active/recent tool executions (Phase 2)
  │   └── session_sidebar.py  Session list with click-to-switch (Phase 4)
  ├── screens/
  │   └── ask_user_modal.py   Modal dialog for ask_user (Phase 3)
  └── styles/
      └── app.tcss        Layout and theming
```

### Event flow

```
User types → InputArea → TextualApp.on_input_submitted()
  → asyncio.create_task(agent.run(text))
    → TurnEngine → LLM stream
      → TextualChannel.emit_text_delta() → ChatLog.append_text()
      → TextualChannel.emit_tool_started() → ToolPanel.add_entry()
      → TextualChannel.ask_user() → push AskUserModal → await Future
      → TextualChannel.emit_turn_complete() → StatusBar.update()
```

### Threading model

Both the agent and Textual are asyncio-based. The agent's `run()` is called via `asyncio.create_task` from within the Textual app's event loop. `TextualChannel` methods update widgets using `App.call_from_thread` if invoked from a worker thread, or direct mutation if on the event loop.

---

## 5. Dependencies

| Package | Version | Purpose | Size |
|---------|---------|---------|------|
| `textual` | `>=1.0` | TUI framework | ~5 MB |

Optional dependency — installed via `pip install -e ".[tui]"`. The `--tui` flag checks for the import at runtime and prints a clear install instruction if missing.

Textual depends on Rich (already a project dependency), so no transitive surprises.

---

## 6. Files Changed Per Phase

### Phase 1

| File | Change |
|------|--------|
| `pyproject.toml` | Add `tui` optional dependency group |
| `src/micro_x_agent_loop/tui/__init__.py` | Package init |
| `src/micro_x_agent_loop/tui/app.py` | New — `TextualApp` |
| `src/micro_x_agent_loop/tui/channel.py` | New — `TextualChannel` |
| `src/micro_x_agent_loop/tui/widgets/chat_log.py` | New |
| `src/micro_x_agent_loop/tui/widgets/input_area.py` | New |
| `src/micro_x_agent_loop/tui/widgets/status_bar.py` | New |
| `src/micro_x_agent_loop/tui/styles/app.tcss` | New |
| `src/micro_x_agent_loop/__main__.py` | Add `--tui` flag parsing |
| `src/micro_x_agent_loop/cli/dispatch.py` | Route `--tui` to `TextualApp` |
| `tests/test_textual_channel.py` | New |
| `tests/test_textual_app.py` | New |

### Phases 2–5

New files only (one widget or screen per phase) plus updates to `tui/app.py`, `tui/channel.py`, `tui/styles/app.tcss`, and test files.

---

## 7. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Textual pre-1.0 API churn | Medium — breaking changes between minor versions | Pin to a specific minor version; isolate all Textual code in `tui/` package |
| asyncio integration complexity | Medium — agent loop and Textual event loop must coexist | Both are asyncio-native; agent.run() as a task within the Textual loop |
| Terminal compatibility | Low — some terminals may not support Textual's rendering | `--tui` is opt-in; default REPL always available as fallback |
| Widget state management during ask_user | Medium — modal must pause agent without deadlock | Use `asyncio.Future` — modal sets result on submit, channel awaits it |
| Testing coverage | Low — Textual's pilot framework is new to the project | Phase 1 includes test infrastructure; expand in later phases |
| Windows Terminal support | Low — Textual supports Windows Terminal natively | Test on Windows as part of Phase 1 acceptance |

---

## 8. What Does NOT Change

- `Agent`, `TurnEngine`, providers, tools, memory, config — zero modifications
- `AgentChannel` protocol — no new methods required
- `TerminalChannel`, `BufferedChannel`, `BrokerChannel`, `WebSocketChannel` — untouched
- `--run`, `--server`, `--broker` modes — untouched
- `cli/repl.py`, `terminal_renderer.py`, `terminal_prompter.py` — remain as the default CLI
- All existing tests — no regressions

---

## 9. Success Criteria

| Phase | Criterion |
|-------|-----------|
| 1 | Multi-turn conversation works in `--tui` mode with streamed markdown, cost status, Escape cancel, slash commands |
| 2 | Tool calls visible in a toggleable right panel with name, timing, and status |
| 3 | `ask_user` renders as a modal overlay; selected answer flows back to the agent |
| 4 | Sessions listed in a toggleable left sidebar; click-to-switch loads history |
| 5 | Command palette discovers slash commands; layout adapts to terminal width |
| All | `mypy src/` clean, `ruff check` clean, all tests pass, no regressions in existing modes |
