# ADR-022: Textual TUI for CLI

## Status

Accepted — 2026-04-02

## Context

The current interactive CLI is assembled from three separate libraries and modules:

| Concern | Current implementation |
|---------|----------------------|
| Input | `prompt_toolkit` (`PromptSession` in `cli/repl.py`) |
| Output | `rich` (`Live` + `Markdown` rendering in `terminal_renderer.py`) |
| Prompts | `questionary` (selection lists and free-text in `terminal_prompter.py`) |

This works but has limitations:

1. **Output replaces itself.** `rich.Live` re-renders the entire markdown buffer on every token delta, then finalises by printing the completed block. There is no persistent scrollback — if the terminal scrolls during a long response, earlier content is gone from the rendered view.

2. **Tool execution is opaque.** Running tools show as a single inline spinner (`⠋ Running tool_name...`). There is no way to see which tools ran previously, how long they took, or whether they errored — that information vanishes when the spinner stops.

3. **`ask_user` interrupts the stream.** When the LLM invokes `ask_user`, the Rich renderer must be torn down (`finalize_text` → `stop`), questionary takes over the terminal, and then the renderer restarts. This causes visual flicker and breaks the reading flow.

4. **No spatial layout.** Everything is a single column of text. Cost/session status is confined to a prompt_toolkit bottom toolbar string. There is no room for a session sidebar, tool activity panel, or persistent system status area.

5. **Three rendering systems.** `prompt_toolkit` owns the input line and toolbar, `rich.Live` owns the output area, and `questionary` takes over the full terminal for prompts. Coordinating between them requires careful lifecycle management (`begin_streaming`/`end_streaming`, `_stop_spinner`, `_ensure_renderer`).

[Textual](https://textual.textualize.io/) is a TUI framework by the same Textualize team that built Rich. It provides a widget-based layout system with CSS styling, async event handling, and built-in widgets (text areas, data tables, trees, command palette). It uses Rich internally for rendering.

### Options considered

1. **Keep the current stack.** Accept the limitations. Low effort, no new dependencies, but the CLI experience stays flat.

2. **Extend the current stack.** Add split-pane rendering with `rich.Layout`, replace questionary with custom prompt_toolkit dialogs, build a tool-history panel manually. This would replicate much of what Textual already provides while fighting three independent library lifecycles.

3. **Adopt Textual as an opt-in TUI mode.** Add `textual` as an optional dependency. Build a `TextualApp` that implements the existing `AgentChannel` protocol. Launch it behind a `--tui` flag. Keep the existing REPL as the default.

4. **Replace the CLI entirely with Textual.** Make Textual the only interactive mode. Simpler to maintain long-term but forces all users onto a full TUI and drops the lightweight REPL fallback.

## Decision

Adopt **option 3**: Textual as an opt-in TUI launched via `--tui`, with the existing REPL remaining the default.

Reasons:

- **Zero changes to agent core.** The `AgentChannel` protocol already decouples the agent from presentation. A new `TextualChannel` is just another implementation alongside `TerminalChannel`, `BufferedChannel`, `BrokerChannel`, and `WebSocketChannel`.

- **Additive, not disruptive.** The existing REPL, `--run` mode, `--server` mode, and `--broker` mode are completely unaffected. Users who prefer a simple terminal or run in constrained environments (SSH, CI, screen readers) keep the current experience.

- **Same ecosystem.** Textual is built on Rich, which is already a dependency. The rendering primitives (Markdown, syntax highlighting, styling) carry over. No new rendering paradigm to learn.

- **Solves real UX gaps.** A widget-based layout directly addresses the five limitations above: persistent scrollback in a chat panel, a dedicated tool activity area, modal `ask_user` dialogs, spatial layout for status/session info, and a single unified rendering system.

### Architecture

```
__main__.py
  ├── --tui flag → TextualApp.run()
  └── (default)  → run_repl()  (unchanged)

TextualApp (textual.App)
  ├── ChatLog widget        — scrollable conversation history (markdown rendered)
  ├── ToolPanel widget      — active/recent tool executions with status
  ├── InputArea widget      — multi-line text input (replaces prompt_toolkit)
  ├── StatusBar widget      — cost, tokens, session info (replaces bottom toolbar)
  ├── SessionSidebar widget — session list, switch, fork (optional, toggle-able)
  └── AskUserModal screen   — modal dialog for ask_user (replaces questionary)

TextualChannel (AgentChannel)
  ├── emit_text_delta()        → post message to ChatLog widget
  ├── emit_tool_started()      → add entry to ToolPanel
  ├── emit_tool_completed()    → update ToolPanel entry
  ├── emit_turn_complete()     → update StatusBar
  ├── emit_error()             → styled error in ChatLog
  ├── emit_system_message()    → system message in ChatLog
  └── ask_user()               → push AskUserModal screen, await result
```

The `TextualChannel` bridges the async agent loop and the Textual event loop. Since both are asyncio-based, `emit_*` methods use `App.call_from_thread` or direct widget mutation (if called from the same event loop). `ask_user` pushes a modal `Screen` and returns an `asyncio.Future` that resolves when the user submits.

### New files

| File | Purpose |
|------|---------|
| `src/micro_x_agent_loop/tui/app.py` | `TextualApp` — main Textual application |
| `src/micro_x_agent_loop/tui/channel.py` | `TextualChannel` — `AgentChannel` implementation |
| `src/micro_x_agent_loop/tui/widgets/` | Custom widgets (chat log, tool panel, input area) |
| `src/micro_x_agent_loop/tui/screens/` | Modal screens (ask_user dialog) |
| `src/micro_x_agent_loop/tui/styles/` | TCSS stylesheets |

### Dependency

`textual` added as an optional dependency in `pyproject.toml`:

```toml
[project.optional-dependencies]
tui = ["textual>=1.0"]
```

Install with `pip install -e ".[tui]"`. The `--tui` flag checks for the import and gives a clear error if not installed.

### Key bindings

| Key | Action |
|-----|--------|
| `Enter` | Submit input |
| `Shift+Enter` / `Esc, Enter` | Newline in input |
| `Escape` | Cancel running turn (maps to existing `EscWatcher`) |
| `Ctrl+P` | Toggle command palette (built-in Textual feature) |
| `Ctrl+S` | Toggle session sidebar |
| `Ctrl+T` | Toggle tool panel |

### Phased delivery

1. **Phase 1 — Core chat.** `TextualApp` with `ChatLog`, `InputArea`, `StatusBar`, and `TextualChannel`. Functional parity with the current REPL for basic conversation.

2. **Phase 2 — Tool panel.** `ToolPanel` widget showing active and recent tool calls with timing and status.

3. **Phase 3 — `ask_user` modal.** `AskUserModal` screen replacing questionary for human-in-the-loop interactions.

4. **Phase 4 — Session sidebar.** Sidebar for session management (list, switch, fork, rename) replacing `/session` slash commands.

5. **Phase 5 — Polish.** Command palette integration for slash commands, theming, responsive layout for narrow terminals.

## Consequences

### Positive

- Persistent, scrollable conversation history with proper markdown rendering.
- Dedicated tool execution panel — visibility into what the agent is doing.
- Clean `ask_user` UX via modal dialogs instead of terminal takeover.
- Spatial layout allows simultaneous display of chat, tools, cost, and session info.
- Single rendering system (Textual) replaces three coordinated libraries.
- Built-in command palette provides discoverability for slash commands.
- Opt-in — zero impact on existing users, modes, or tests.

### Negative

- New dependency (~5 MB), though from the same team as the existing Rich dependency.
- More code to maintain (TUI app + widgets + styles + channel).
- Textual is still pre-1.0 (rapid development, possible breaking changes between minor versions).
- Full TUI may not work well over very slow SSH connections or in terminals with limited capability (though the existing REPL remains available as fallback).
- Testing the TUI requires Textual's pilot testing framework — a new testing pattern to learn.

### Neutral

- The existing `TerminalChannel`, `RichRenderer`, `PlainSpinner`, and `terminal_prompter` remain unchanged and continue to serve the default REPL mode.
- The `AgentChannel` protocol requires no modifications.
- Config system unchanged — no new config keys needed for phase 1 (theming/layout preferences may come later).

## Appendix: Layout Wireframes

### Phase 1 — Core Chat

Minimal layout: scrollable chat log, multi-line input area, status bar.

```
┌─────────────────────────────────────────────────────────────────────┐
│  MICRO-X AGENT  │  anthropic:claude-sonnet-4-20250514  │  session: a3f8c2  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  you>                                                               │
│  What files changed in the last 3 commits?                          │
│                                                                     │
│  assistant>                                                         │
│  Here are the files changed in the last 3 commits:                  │
│                                                                     │
│  **Commit 9a4a41b** — `refactor: fix SRP violations`               │
│  - `src/micro_x_agent_loop/agent.py`                                │
│  - `src/micro_x_agent_loop/turn_engine.py`                          │
│  - `tests/test_cost_reduction.py`                                   │
│                                                                     │
│  **Commit 422b4a7** — `docs: add coding standards guide`           │
│  - `documentation/docs/guides/coding-standards.md`                  │
│                                                                     │
│  **Commit 4d62060** — `docs: add ISSUE-004 audit`                  │
│  - `documentation/docs/issues/ISSUE-004-solid-dry-kiss-...md`       │
│                                                                     │
│  you>                                                               │
│  Can you refactor the turn_engine to extract the tool dispatch      │
│  logic into its own module?                                         │
│                                                                     │
│  assistant>                                                         │
│  ⠹ Thinking...                                                      │
│                                                                     │
│                                                                     │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ you> █                                                              │
│                                                                     │
│                                                          [Esc:stop] │
├─────────────────────────────────────────────────────────────────────┤
│ T3 │ $0.0142 │ ↑12.4k ↓1.2k tokens │ ctx: 14,832 │ 3 msgs        │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 2 — Tool Panel

Right sidebar shows active and recent tool executions with timing and status.

```
┌──────────────────────────────────────────────────┬──────────────────┐
│  MICRO-X AGENT  │  anthropic:claude-sonnet-4-20250514  │  a3f8c2   │    Tools         │
├──────────────────────────────────────────────────┤──────────────────┤
│                                                  │                  │
│  you>                                            │  ● read_file     │
│  Read the config and suggest improvements        │    1.2s ✓        │
│                                                  │                  │
│  assistant>                                      │  ● grep_search   │
│  Let me look at the config file first.           │    0.8s ✓        │
│                                                  │                  │
│  I've reviewed `config-base.json`. Here are      │  ⠹ write_file   │
│  three suggestions:                              │    running...    │
│                                                  │                  │
│  1. **Move pricing to a separate file.**         │                  │
│     The `Pricing` block is 40 lines and          │                  │
│     changes independently from routing.          │                  │
│                                                  │                  │
│  2. **Add JSON schema validation.**              │                  │
│     A `$schema` reference would catch typos      │                  │
│     before runtime.                              │                  │
│                                                  │                  │
│  3. **Default `Temperature` per routing          │                  │
│     policy.** Currently global only.             │                  │
│                                                  │                  │
│  Shall I implement any of these?                 │                  │
│                                                  │                  │
├──────────────────────────────────────────────────┤──────────────────┤
│ you> █                                           │                  │
│                                                  │                  │
├──────────────────────────────────────────────────┴──────────────────┤
│ T5 │ $0.0318 │ ↑28.1k ↓3.4k tokens │ ctx: 31,204 │ 9 msgs        │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 3 — ask_user Modal

Centered modal overlay for human-in-the-loop questions with radio options and free-text escape hatch.

```
┌──────────────────────────────────────────────────┬──────────────────┐
│  MICRO-X AGENT  │  anthropic:claude-sonnet-4-20250514  │  a3f8c2   │    Tools         │
├──────────────────────┬───────────────────────────┤──────────────────┤
│                      │                           │                  │
│  assistant>          │ ┌───────────────────────┐ │  ● read_file     │
│  I need to know whi  │ │                       │ │    1.2s ✓        │
│  approach you prefer │ │  🤖 Agent Question    │ │                  │
│                      │ │                       │ │  ● grep_search   │
│                      │ │  Which approach do    │ │    0.8s ✓        │
│                      │ │  you prefer for the   │ │                  │
│                      │ │  config refactor?     │ │                  │
│                      │ │                       │ │                  │
│                      │ │  ○ Separate file      │ │                  │
│                      │ │    Move pricing to    │ │                  │
│                      │ │    pricing.json       │ │                  │
│                      │ │                       │ │                  │
│                      │ │  ● Inline with refs   │ │                  │
│                      │ │    Keep in config,    │ │                  │
│                      │ │    add $ref pointers  │ │                  │
│                      │ │                       │ │                  │
│                      │ │  ┌─────────────────┐  │ │                  │
│                      │ │  │    Submit        │  │ │                  │
│                      │ │  └─────────────────┘  │ │                  │
│                      │ │  Or type your own:    │ │                  │
│                      │ │  ┌─────────────────┐  │ │                  │
│                      │ │  │                 │  │ │                  │
│                      │ │  └─────────────────┘  │ │                  │
│                      │ └───────────────────────┘ │                  │
├──────────────────────┴───────────────────────────┴──────────────────┤
│ T5 │ $0.0318 │ ↑28.1k ↓3.4k tokens │ ctx: 31,204 │ 9 msgs        │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 4 — Session Sidebar

Left sidebar for session management. Toggled with Ctrl+S.

```
┌─────────────────────────────────────────────────────────────────────┐
│  MICRO-X AGENT  │  anthropic:claude-sonnet-4-20250514               │
├────────────┬─────────────────────────────────────┬──────────────────┤
│  Sessions  │                                     │    Tools         │
│            │  you>                                │                  │
│  ● a3f8c2  │  Can you refactor the tool          │  ● read_file     │
│  "config   │  dispatch into its own module?       │    1.2s ✓        │
│   refactor"│                                     │                  │
│  Apr 2     │  assistant>                          │  ● grep_search   │
│            │  Sure. I'll extract the tool         │    0.8s ✓        │
│  ○ 7b2e91  │  dispatch loop from `turn_engine`   │                  │
│  "routing  │  into `tool_dispatch.py`...          │                  │
│   tests"   │                                     │                  │
│  Apr 1     │                                     │                  │
│            │                                     │                  │
│  ○ f4d103  │                                     │                  │
│  "initial  │                                     │                  │
│   setup"   │                                     │                  │
│  Mar 30    │                                     │                  │
│            │                                     │                  │
│ ────────── │                                     │                  │
│ + New      │                                     │                  │
│ ⑂ Fork     │                                     │                  │
├────────────┼─────────────────────────────────────┤──────────────────┤
│            │ you> █                               │                  │
├────────────┴─────────────────────────────────────┴──────────────────┤
│ T5 │ $0.0318 │ ↑28.1k ↓3.4k │ ctx: 31k │ 9 msgs │ Ctrl+P: cmds   │
└─────────────────────────────────────────────────────────────────────┘
```

### Key UX properties

- **Chat log scrolls independently** — earlier messages persist and can be scrolled back to.
- **Tool panel** shows what ran, how long it took, and whether it succeeded — all at a glance.
- **ask_user** is a centered modal overlay, not a full terminal takeover.
- **Session sidebar** replaces `/session list` + `/session resume` with clickable navigation.
- **Status bar** is always visible with live cost/token counters.
- **Panels are toggle-able** — Ctrl+S and Ctrl+T show/hide sidebars, so narrow terminals show only the chat.
