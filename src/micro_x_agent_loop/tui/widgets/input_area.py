"""InputArea widget — multi-line text input with submit/newline bindings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input


class InputArea(Widget):
    """Single-line input at the bottom of the TUI.

    Enter submits the message.
    """

    DEFAULT_CSS = """
    InputArea {
        height: 3;
        dock: bottom;
        padding: 0 1;
    }

    InputArea Input {
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    class Submitted(Message):
        """Posted when the user submits their input."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class CancelRequested(Message):
        """Posted when the user presses Escape."""

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        inp = Input(placeholder="you> ", id="input-field")
        self._input = inp
        yield inp

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter — submit the message."""
        text = event.value.strip()
        if text:
            self.post_message(self.Submitted(text))
        if self._input is not None:
            self._input.value = ""

    def on_key(self, event: Key) -> None:
        """Handle Escape to cancel."""
        if event.key == "escape":
            self.post_message(self.CancelRequested())

    def focus_input(self) -> None:
        """Focus the input."""
        if self._input is not None:
            self._input.focus()

    @property
    def is_empty(self) -> bool:
        return self._input is None or not self._input.value.strip()

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable the input."""
        if self._input is not None:
            self._input.disabled = disabled
