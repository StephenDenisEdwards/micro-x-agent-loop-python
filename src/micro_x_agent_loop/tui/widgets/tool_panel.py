"""ToolPanel widget — right sidebar showing active and recent tool executions."""

from __future__ import annotations

import time
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class _ToolEntry(Static):
    """A single tool execution entry."""

    DEFAULT_CSS = """
    _ToolEntry {
        height: auto;
        padding: 0 1;
    }
    """


class ToolPanel(VerticalScroll):
    """Scrollable panel showing tool execution history for the current turn."""

    DEFAULT_CSS = """
    ToolPanel {
        width: 38;
        height: 1fr;
        border-left: solid $primary;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._active_tools: dict[str, tuple[str, float, dict[str, Any] | None]] = {}
        # tool_use_id → (tool_name, start_time, tool_input)

    # ------------------------------------------------------------------ events

    def tool_started(
        self,
        tool_use_id: str,
        tool_name: str,
        *,
        tool_input: dict[str, Any] | None = None,
    ) -> None:
        """Record a tool starting execution."""
        self._active_tools[tool_use_id] = (tool_name, time.monotonic(), tool_input)
        arg_summary = _summarise_args(tool_name, tool_input)
        body = f"[cyan]>>>[/cyan] {escape(tool_name)}"
        if arg_summary:
            body += f"\n    [dim]{escape(arg_summary)}[/dim]"
        entry = _ToolEntry(body, id=f"tool-{tool_use_id}")
        self.mount(entry)
        self.scroll_end(animate=False)

    def tool_completed(
        self,
        tool_use_id: str,
        tool_name: str,
        is_error: bool,
        *,
        result_chars: int = 0,
        was_summarized: bool = False,
        was_truncated: bool = False,
        duration_ms: float = 0.0,
    ) -> None:
        """Update a tool entry with completion status, duration, and result metadata."""
        elapsed_str = _format_duration(duration_ms)
        tool_input: dict[str, Any] | None = None
        if tool_use_id in self._active_tools:
            _, start_time, tool_input = self._active_tools.pop(tool_use_id)
            if duration_ms <= 0:
                elapsed_str = _format_duration((time.monotonic() - start_time) * 1000)

        try:
            entry = self.query_one(f"#tool-{tool_use_id}", _ToolEntry)
        except Exception:
            entry = _ToolEntry(id=f"tool-{tool_use_id}")
            self.mount(entry)

        status = "[red]ERR[/red]" if is_error else "[green] ok[/green]"
        lines = [f"{status} {escape(tool_name)}  [dim]{elapsed_str}[/dim]"]

        arg_summary = _summarise_args(tool_name, tool_input)
        if arg_summary:
            lines.append(f"    [dim]{escape(arg_summary)}[/dim]")

        # Result line: size + badges
        if result_chars or was_summarized or was_truncated:
            size = _format_size(result_chars)
            badges: list[str] = []
            if was_truncated:
                badges.append("[yellow]trunc[/yellow]")
            if was_summarized:
                badges.append("[yellow]summ[/yellow]")
            badge_str = (" " + " ".join(badges)) if badges else ""
            lines.append(f"    [dim]→ {size}[/dim]{badge_str}")

        entry.update("\n".join(lines))
        self.scroll_end(animate=False)

    def clear_entries(self) -> None:
        """Clear all tool entries (e.g. between turns)."""
        self._active_tools.clear()
        for entry in self.query(_ToolEntry):
            entry.remove()

    def load_history(self, tool_calls: list[dict[str, object]]) -> None:
        """Populate the panel with historical tool calls from the database."""
        self.clear_entries()
        for tc in tool_calls:
            name = str(tc.get("tool_name", "unknown"))
            is_error = bool(tc.get("is_error", 0))
            status = "[red]ERR[/red]" if is_error else "[green] ok[/green]"
            entry = _ToolEntry(f"{status} {escape(name)}")
            self.mount(entry)
        if tool_calls:
            self.scroll_end(animate=False)

    def compose(self) -> ComposeResult:
        yield Static("[bold]Tools[/bold]", classes="tool-panel-title")


# ------------------------------------------------------------------ helpers


# Per-tool: which input keys to surface in the short args summary, in order.
# First non-empty key wins; if none match, the first key/value pair is used.
_ARG_KEYS_BY_TOOL: dict[str, tuple[str, ...]] = {
    "web__web_fetch": ("url",),
    "filesystem__bash": ("command",),
    "filesystem__grep": ("pattern", "path"),
    "filesystem__read_file": ("path",),
    "filesystem__glob": ("pattern", "path"),
    "filesystem__write_file": ("path",),
    "filesystem__edit_file": ("path",),
    "filesystem__delete_file": ("path",),
    "google__gmail_search": ("query",),
    "google__gmail_read": ("messageId",),
    "playwright__browser_navigate": ("url",),
    "playwright__browser_click": ("target",),
}


def _summarise_args(tool_name: str, tool_input: dict[str, Any] | None) -> str:
    """Pick the most informative arg or two from ``tool_input`` for display."""
    if not tool_input:
        return ""
    keys = _ARG_KEYS_BY_TOOL.get(tool_name, ())
    parts: list[str] = []
    for key in keys:
        if key in tool_input and tool_input[key]:
            parts.append(f"{key}={_short(tool_input[key])}")
            if len(parts) >= 2:
                break
    if not parts:
        # Fallback: show the first key with a non-empty value
        for k, v in tool_input.items():
            if v not in (None, "", [], {}):
                parts.append(f"{k}={_short(v)}")
                break
    return "  ".join(parts)


def _short(v: Any, limit: int = 28) -> str:
    s = str(v)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _format_size(n: int) -> str:
    if n <= 0:
        return "0 chars"
    if n < 1024:
        return f"{n} chars"
    if n < 1024 * 1024:
        return f"{n // 1024} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _format_duration(ms: float) -> str:
    if ms <= 0:
        return ""
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"
