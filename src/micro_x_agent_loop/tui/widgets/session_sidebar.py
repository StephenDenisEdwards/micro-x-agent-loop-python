"""SessionSidebar widget — left sidebar for session management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from micro_x_agent_loop.memory.session_manager import SessionManager


class SessionSidebar(Vertical):
    """Left sidebar listing sessions with click-to-switch, new, and fork."""

    DEFAULT_CSS = """
    SessionSidebar {
        width: 28;
        height: 1fr;
        border-right: solid $primary;
        display: none;
    }

    .sidebar-title {
        text-style: bold;
        padding: 0 1;
        color: $text-muted;
        height: 1;
    }

    .session-list {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    .session-entry {
        height: auto;
        padding: 0 1;
    }

    .session-entry:hover {
        background: $primary 20%;
    }

    .session-active {
        color: $text;
        text-style: bold;
    }

    .session-inactive {
        color: $text-muted;
    }

    .sidebar-buttons {
        height: auto;
        padding: 0 1;
    }

    .sidebar-buttons Button {
        width: 100%;
        margin: 0 0 0 0;
        min-width: 10;
    }
    """

    class SessionSelected(Message):
        """Posted when a session is clicked."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class NewSessionRequested(Message):
        """Posted when the New button is clicked."""

    class ForkSessionRequested(Message):
        """Posted when the Fork button is clicked."""

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._active_session_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("[bold]Sessions[/bold]", classes="sidebar-title")
        yield VerticalScroll(classes="session-list", id="session-list-scroll")
        with Vertical(classes="sidebar-buttons"):
            yield Button("+ New", id="btn-new-session", variant="default")
            yield Button("Fork", id="btn-fork-session", variant="default")

    def refresh_sessions(
        self,
        session_manager: SessionManager | None,
        active_session_id: str | None,
    ) -> None:
        """Reload the session list from the database."""
        self._active_session_id = active_session_id
        scroll = self.query_one("#session-list-scroll", VerticalScroll)

        # Remove existing entries
        for entry in list(scroll.query(".session-entry")):
            entry.remove()

        if session_manager is None:
            scroll.mount(Static("[dim]Memory disabled[/dim]", classes="session-entry"))
            return

        sessions = session_manager.list_sessions(limit=20)
        if not sessions:
            scroll.mount(Static("[dim]No sessions[/dim]", classes="session-entry"))
            return

        for s in sessions:
            sid = s["id"]
            title = s.get("title", sid[:8])
            date = s.get("updated_at", s.get("created_at", ""))[:10]
            is_active = sid == active_session_id

            if is_active:
                label = f"[bold cyan]> {escape(title)}[/bold cyan]\n  [dim]{date}[/dim]"
                css_class = "session-entry session-active"
            else:
                label = f"  {escape(title)}\n  [dim]{date}[/dim]"
                css_class = "session-entry session-inactive"

            entry = _ClickableSession(label, session_id=sid, classes=css_class)
            scroll.mount(entry)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new-session":
            self.post_message(self.NewSessionRequested())
        elif event.button.id == "btn-fork-session":
            self.post_message(self.ForkSessionRequested())

    def on_click(self, event: Any) -> None:
        """Bubble up session clicks from child entries."""
        # Handled by _ClickableSession via message posting


class _ClickableSession(Static):
    """A session entry that posts SessionSelected when clicked."""

    def __init__(self, label: str, *, session_id: str, classes: str = "") -> None:
        super().__init__(label, classes=classes)
        self._session_id = session_id

    def on_click(self) -> None:
        self.post_message(SessionSidebar.SessionSelected(self._session_id))
