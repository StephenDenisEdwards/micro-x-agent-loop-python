"""ChatLog widget — scrollable conversation history with markdown rendering."""

from __future__ import annotations

from typing import Any

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


def _extract_text(content: object) -> str:
    """Extract plain text from a message content field.

    Content can be a string or a list of blocks (Anthropic format):
    ``[{"type": "text", "text": "..."}, {"type": "tool_use", "name": "..."}]``
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append(str(block.get("text", "")))
        elif block_type == "tool_use":
            name = block.get("name", "tool")
            parts.append(f"[tool: {name}]")
        elif block_type == "tool_result":
            # Skip tool results in history — too verbose
            continue
    return "\n".join(parts)


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

    def add_assistant_history(self, text: str) -> None:
        """Append a completed assistant message from history (rendered as markdown)."""
        md = Markdown(text, classes="assistant-message")
        self.mount(md)

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

    def add_banner(self, markup: str) -> None:
        """Append pre-formatted Rich markup (no escaping). Used for the startup logo."""
        block = Static(markup, classes="system-message")
        self.mount(block)
        self.scroll_end(animate=False)

    def add_error_message(self, text: str) -> None:
        """Append an error message."""
        block = Static(f"[bold red]Error:[/bold red] {escape(text)}", classes="error-message")
        self.mount(block)
        self.scroll_end(animate=False)

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        """Clear the chat log and populate it with historical messages."""
        # Remove all existing children
        for child in list(self.children):
            child.remove()

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            text = _extract_text(content)
            if not text.strip():
                continue

            if role == "user":
                self.add_user_message(text)
            elif role == "assistant":
                self.add_assistant_history(text)

        self.scroll_end(animate=False)

    def compose(self) -> ComposeResult:
        """Initial empty composition."""
        yield from ()
