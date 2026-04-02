"""ToolPanel widget — right sidebar showing active and recent tool executions."""

from __future__ import annotations

import time

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
        width: 30;
        height: 1fr;
        border-left: solid $primary;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._active_tools: dict[str, tuple[str, float]] = {}  # tool_use_id → (tool_name, start_time)

    def tool_started(self, tool_use_id: str, tool_name: str) -> None:
        """Record a tool starting execution."""
        self._active_tools[tool_use_id] = (tool_name, time.monotonic())
        entry = _ToolEntry(
            f"[cyan]>>>[/cyan] {escape(tool_name)}",
            id=f"tool-{tool_use_id}",
        )
        self.mount(entry)
        self.scroll_end(animate=False)

    def tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        """Update a tool entry with completion status and duration."""
        duration_str = ""
        if tool_use_id in self._active_tools:
            _, start_time = self._active_tools.pop(tool_use_id)
            elapsed = time.monotonic() - start_time
            if elapsed >= 1.0:
                duration_str = f" {elapsed:.1f}s"
            else:
                duration_str = f" {elapsed * 1000:.0f}ms"

        try:
            entry = self.query_one(f"#tool-{tool_use_id}", _ToolEntry)
        except Exception:
            # Entry not found — add a new one
            entry = _ToolEntry(id=f"tool-{tool_use_id}")
            self.mount(entry)

        if is_error:
            entry.update(f"[red]ERR[/red] {escape(tool_name)}{duration_str}")
        else:
            entry.update(f"[green] ok[/green] {escape(tool_name)}{duration_str}")
        self.scroll_end(animate=False)

    def clear_entries(self) -> None:
        """Clear all tool entries (e.g. between turns)."""
        self._active_tools.clear()
        for entry in self.query(_ToolEntry):
            entry.remove()

    def compose(self) -> ComposeResult:
        yield Static("[bold]Tools[/bold]", classes="tool-panel-title")
