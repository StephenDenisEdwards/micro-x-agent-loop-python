"""ChatLog widget — scrollable conversation history with markdown rendering."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static


class _MessageBlock(Static):
    """A single message in the chat log (user, assistant, system, or error)."""

    DEFAULT_CSS = """
    _MessageBlock {
        margin: 0 1;
        padding: 0 1;
    }
    """


class ChatLog(VerticalScroll):
    """Scrollable container of conversation messages."""

    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._streaming_md: Markdown | None = None
        self._streaming_buffer: str = ""
        self._spinner: Static | None = None

    def add_user_message(self, text: str) -> None:
        """Append a user message."""
        block = _MessageBlock(classes="user-message")
        block.update(f"[bold cyan]you>[/bold cyan] {escape(text)}")
        self.mount(block)
        self.scroll_end(animate=False)

    def begin_assistant_message(self) -> None:
        """Start an assistant response — show thinking spinner."""
        self._streaming_buffer = ""
        self._spinner = Static("[cyan]assistant> [dim]Thinking...[/dim][/cyan]", classes="thinking-spinner")
        self.mount(self._spinner)
        self.scroll_end(animate=False)

    def append_text(self, text: str) -> None:
        """Append streaming text to the current assistant message."""
        if self._spinner is not None:
            self._spinner.remove()
            self._spinner = None
            self._streaming_md = Markdown("", classes="assistant-message")
            self.mount(self._streaming_md)

        if self._streaming_md is None:
            self._streaming_md = Markdown("", classes="assistant-message")
            self.mount(self._streaming_md)

        self._streaming_buffer += text
        self._streaming_md.update(self._streaming_buffer)
        self.scroll_end(animate=False)

    def finalize_assistant_message(self) -> None:
        """Finalize the current assistant message."""
        if self._spinner is not None:
            self._spinner.remove()
            self._spinner = None
        self._streaming_md = None
        self._streaming_buffer = ""

    def add_tool_message(self, tool_name: str, status: str) -> None:
        """Show an inline tool status line."""
        block = Static(f"  [dim]{escape(status)} {escape(tool_name)}[/dim]", classes="tool-inline")
        self.mount(block)
        self.scroll_end(animate=False)

    def add_system_message(self, text: str) -> None:
        """Append a system message."""
        block = Static(f"[dim]{escape(text)}[/dim]", classes="system-message")
        self.mount(block)
        self.scroll_end(animate=False)

    def add_error_message(self, text: str) -> None:
        """Append an error message."""
        block = Static(f"[bold red]Error:[/bold red] {escape(text)}", classes="error-message")
        self.mount(block)
        self.scroll_end(animate=False)

    def compose(self) -> ComposeResult:
        """Initial empty composition."""
        yield from ()
