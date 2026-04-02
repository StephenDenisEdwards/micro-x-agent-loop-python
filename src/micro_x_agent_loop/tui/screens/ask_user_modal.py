"""AskUserModal — modal dialog for human-in-the-loop ask_user questions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet


class AskUserModal(ModalScreen[str]):
    """Centered modal for ask_user questions.

    Displays the question, optional radio options, a free-text input,
    and a submit button. Returns the selected/typed answer as the screen result.
    """

    CSS = """
    AskUserModal {
        align: center middle;
    }

    #ask-user-dialog {
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #ask-user-question {
        margin-bottom: 1;
        text-style: bold;
    }

    #ask-user-options {
        margin-bottom: 1;
    }

    #ask-user-free-text {
        margin-top: 1;
        margin-bottom: 1;
    }

    #ask-user-submit {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        question: str,
        options: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self._question = question
        self._options = options or []

    def compose(self) -> ComposeResult:
        with Vertical(id="ask-user-dialog"):
            yield Label(self._question, id="ask-user-question")

            if self._options:
                with RadioSet(id="ask-user-options"):
                    for i, opt in enumerate(self._options):
                        label = opt.get("label", "")
                        desc = opt.get("description", "")
                        display = f"{label} — {desc}" if desc else label
                        yield RadioButton(display, value=i == 0, id=f"opt-{i}")

                yield Label("Or type your own:", id="ask-user-free-label")

            yield Input(
                placeholder="Type your answer..." if self._options else "Your answer...",
                id="ask-user-free-text",
            )
            yield Button("Submit", variant="primary", id="ask-user-submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle submit button."""
        if event.button.id == "ask-user-submit":
            self._submit_answer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the free-text input."""
        self._submit_answer()

    def _submit_answer(self) -> None:
        """Resolve the answer from radio selection or free-text input."""
        # Check free-text first — if the user typed something, prefer it
        free_text = self.query_one("#ask-user-free-text", Input).value.strip()
        if free_text:
            self.dismiss(free_text)
            return

        # Check radio selection
        if self._options:
            radio_set = self.query_one("#ask-user-options", RadioSet)
            if radio_set.pressed_index >= 0:
                selected_label = self._options[radio_set.pressed_index].get("label", "")
                self.dismiss(selected_label)
                return

        # Nothing selected — dismiss with empty (caller handles default)
        self.dismiss("")

    def action_cancel(self) -> None:
        """Cancel the modal — return empty string."""
        self.dismiss("")
