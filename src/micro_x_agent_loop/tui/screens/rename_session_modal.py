"""RenameSessionModal — modal dialog for naming/renaming the active session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class RenameSessionModal(ModalScreen[str | None]):
    """Centered modal that asks for a new session title.

    Dismisses with the trimmed string on submit, or ``None`` on cancel.
    """

    CSS = """
    RenameSessionModal {
        align: center middle;
    }

    #rename-dialog {
        width: 60;
        max-width: 80%;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #rename-title {
        margin-bottom: 1;
        text-style: bold;
    }

    #rename-input {
        margin-bottom: 1;
    }

    #rename-buttons {
        height: auto;
        align-horizontal: right;
    }

    #rename-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, current_title: str) -> None:
        super().__init__()
        self._current_title = current_title

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-dialog"):
            yield Label("Rename session", id="rename-title")
            yield Input(
                value=self._current_title,
                placeholder="Session title...",
                id="rename-input",
            )
            with Horizontal(id="rename-buttons"):
                yield Button("Cancel", id="rename-cancel")
                yield Button("Save", variant="primary", id="rename-save")

    def on_mount(self) -> None:
        """Focus the input and select all text so the user can type to replace."""
        input_widget = self.query_one("#rename-input", Input)
        input_widget.focus()
        input_widget.action_select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename-save":
            self._submit()
        elif event.button.id == "rename-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        value = self.query_one("#rename-input", Input).value.strip()
        if not value:
            self.dismiss(None)
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
