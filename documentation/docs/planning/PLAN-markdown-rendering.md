# Plan: Progressive Markdown Rendering

**Status:** Not Started
**Date:** 2026-03-10
**Goal:** Stream markdown-formatted LLM output and render it progressively in the CLI, matching the display quality of ChatGPT and Claude Code.

---

## 1. Problem

The CLI displays raw LLM text via `print(text, end="", flush=True)` — no formatting, no syntax highlighting, no markdown rendering. LLM responses contain markdown (code blocks, bold, lists, tables) but the user sees raw syntax characters.

Web clients receive raw `text_delta` JSON frames and are responsible for their own rendering (no change needed server-side).

---

## 2. Approach: Buffer-and-Rerender

Same technique as ChatGPT CLI and Claude Code:

1. Accumulate streamed tokens into a string buffer
2. On each new token, re-render the entire buffer as markdown
3. Use `rich.Live` to efficiently refresh only the changed terminal region
4. Finalize on turn complete (print final state, release terminal control)

`rich.Markdown` parsing is fast (milliseconds) relative to LLM token generation speed (~50-100 tokens/s), making per-token re-rendering practical. `rich.Live` caps refresh rate (~8/s) to naturally batch rapid updates.

---

## 3. Design

### 3.1 — Replace `_Spinner` with `_RichRenderer`

The current `_Spinner` uses raw `\r` cursor manipulation and `sys.stdout.write`. `rich.Live` also manipulates the terminal via ANSI escape sequences. They cannot coexist — both would fight over cursor position.

**Solution:** Replace `_Spinner` with a `_RichRenderer` class that manages a `rich.Live` context and switches between two renderables:
- **Spinner** (`rich.spinner.Spinner`) — shown during thinking and tool execution
- **Markdown** (`rich.Markdown`) — shown during text streaming

### 3.2 — Segmented Rendering

Don't maintain one `Live` across the entire turn. Use segments:

```
begin_streaming()  →  Spinner segment (thinking)
emit_text_delta()  →  Markdown segment (text streaming, re-rendered per token)
emit_tool_started  →  Finalize markdown (print to terminal), start Spinner segment
emit_tool_completed→  Stop spinner
emit_text_delta()  →  New Markdown segment (fresh buffer, previous text already printed)
emit_turn_complete →  Finalize any active segment
```

When a tool interrupts text, the accumulated markdown is finalized (printed to terminal as rendered output) and a new markdown buffer starts for the next text segment. A code block split across a tool interruption renders as two separate blocks — acceptable and matches how other agents work.

### 3.3 — `_RichRenderer` API

```python
class _RichRenderer:
    def __init__(self, line_prefix: str) -> None: ...
    def start_spinner(self, label: str = " Thinking...") -> None: ...
    def append_text(self, text: str) -> None:       # buffer += text; Live.update(Markdown(buffer))
    def finalize_text(self) -> None:                 # stop Live, buffer is printed as final output
    def print_line(self, text: str) -> None:         # print above the Live region
    def stop(self) -> None:                          # stop Live cleanly
```

### 3.4 — TerminalChannel Changes

All changes are internal to `TerminalChannel`. The `AgentChannel` protocol does not change.

| Method | Before | After |
|--------|--------|-------|
| `begin_streaming()` | Create `_Spinner`, start it | Create `_RichRenderer`, start spinner |
| `emit_text_delta(text)` | `print(text, end="", flush=True)` | `renderer.append_text(text)` (switches from spinner to markdown on first call) |
| `emit_tool_started(...)` | Stop spinner, start new spinner | Finalize markdown, start spinner |
| `emit_tool_completed(...)` | Stop spinner | Stop spinner |
| `emit_turn_complete(...)` | Stop spinner, reset state | Finalize any active segment, reset state |
| `end_streaming()` | Stop spinner | Finalize any active segment |
| `emit_error(message)` | Stop spinner, `print(...)` | Stop renderer, `Console.print(...)` with error styling |
| `emit_system_message(text)` | `print_line(text)` | `renderer.print_line(text)` (prints above Live region) |
| `print_line(text)` | Direct print or spinner print | `renderer.print_line(text)` or `Console.print(text)` |

### 3.5 — Lifecycle: `begin_streaming()` / `end_streaming()`

Currently `begin_streaming()` is only called from `server/client.py`. For the direct REPL, the spinner starts on `emit_tool_started` or not at all.

**Change:** Add `begin_streaming()` call at the start of `Agent._run_inner()` and `end_streaming()` at the end, so both direct REPL and WebSocket client get consistent lifecycle management.

```python
# In Agent._run_inner():
if self._channel is not None and hasattr(self._channel, 'begin_streaming'):
    self._channel.begin_streaming()
try:
    # ... existing turn engine logic ...
finally:
    if self._channel is not None and hasattr(self._channel, 'end_streaming'):
        self._channel.end_streaming()
```

### 3.6 — No WebSocket/Server Changes

The WebSocket API already sends raw `text_delta` frames. Web frontends render markdown client-side (e.g., `react-markdown`, `markdown-it`). No server-side changes needed.

The WebSocket CLI client (`server/client.py`) already uses `TerminalChannel` — it will automatically get markdown rendering through the same changes.

---

## 4. Implementation Steps

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 1 | Add `rich>=13.0.0` to dependencies | `pyproject.toml` | Trivial |
| 2 | Implement `_RichRenderer` class | `agent_channel.py` | Medium |
| 3 | Rewrite `TerminalChannel` to use `_RichRenderer` | `agent_channel.py` | Medium |
| 4 | Delete `_Spinner` class | `agent_channel.py` | Trivial |
| 5 | Add `begin_streaming()`/`end_streaming()` calls in `Agent._run_inner()` | `agent.py` | Small |
| 6 | Clean up `__main__.py` (remove manual newlines after agent.run if present) | `__main__.py` | Small |
| 7 | Verify `server/client.py` works (uses TerminalChannel — should just work) | `server/client.py` | Verify |
| 8 | Update existing tests, add new tests for `_RichRenderer` | `tests/test_ask_user.py`, new `tests/test_terminal_rendering.py` | Medium |

---

## 5. Dependencies

- **`rich>=13.0.0`** — well-maintained (100M+ downloads/month), supports Windows Terminal (ANSI), handles incomplete markdown gracefully. Sub-dependencies: `markdown-it-py`, `pygments` (syntax highlighting).

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Rich + old Windows terminals | Low — Windows 11 Terminal supports full ANSI | Rich auto-detects capabilities; falls back to basic rendering |
| Spinner/Live conflict during transition | Medium — visual glitch | Strict lifecycle: stop one before starting the other |
| Incomplete markdown during streaming | Low — rich renders unclosed fences as plain text | Acceptable — matches ChatGPT/Claude Code behavior |
| Performance on very large responses | Low — markdown parsing is fast | Live refresh rate capped at 8/s; buffer resets per segment |

---

## 7. Success Criteria

- Code blocks render with syntax highlighting in the terminal
- Bold, italic, lists, and tables render correctly
- Streaming feels smooth — no flicker, no visible re-draw artifacts
- Spinner still works during thinking and tool execution
- No regression in non-CLI channels (BufferedChannel, BrokerChannel, WebSocketChannel)
- Existing tests pass; new tests cover the rendering lifecycle
