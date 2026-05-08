"""InputArea widget — multi-line text input that supports pasting."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea


class InputArea(Widget):
    """Multi-line input at the bottom of the TUI.

    - Plain Enter submits the message.
    - Shift+Enter (or Ctrl+J as a fallback for terminals that don't
      forward shift+enter) inserts a newline.
    - Pasted multi-line content is preserved as-is until you submit.
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
        self._textarea: TextArea | None = None

    def compose(self) -> ComposeResult:
        ta = TextArea(id="input-field")
        ta.show_line_numbers = False
        self._textarea = ta
        yield ta

    def on_key(self, event: Key) -> None:
        """Intercept Enter (submit) and Shift+Enter / Ctrl+J (newline)."""
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._submit()
            return
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            if self._textarea is not None:
                self._textarea.insert("\n")
            return
        if event.key == "escape":
            self.post_message(self.CancelRequested())

    def _submit(self) -> None:
        if self._textarea is None:
            return
        text = self._textarea.text.strip()
        if text:
            self.post_message(self.Submitted(text))
        self._textarea.text = ""

    def focus_input(self) -> None:
        """Focus the input."""
        if self._textarea is not None:
            self._textarea.focus()

    @property
    def is_empty(self) -> bool:
        return self._textarea is None or not self._textarea.text.strip()

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable the input."""
        if self._textarea is not None:
            self._textarea.disabled = disabled
