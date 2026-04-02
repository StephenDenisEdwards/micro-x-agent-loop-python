"""ModeChoiceModal — modal for PROMPT/COMPILED mode selection."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet


class ModeChoiceModal(ModalScreen[str]):
    """Modal for choosing between PROMPT and COMPILED execution mode.

    Returns "PROMPT" or "COMPILED" as the screen result.
    """

    CSS = """
    ModeChoiceModal {
        align: center middle;
    }

    #mode-dialog {
        width: 65;
        max-width: 85%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #mode-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .mode-signal {
        margin: 0 0 0 2;
        color: $text-muted;
    }

    #mode-options {
        margin: 1 0;
    }

    .mode-buttons {
        height: auto;
        margin-top: 1;
    }

    .mode-buttons Button {
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        signals: list[str],
        recommended: str,
        reasoning: str = "",
    ) -> None:
        super().__init__()
        self._signals = signals
        self._recommended = recommended
        self._reasoning = reasoning

    def compose(self) -> ComposeResult:
        with Vertical(id="mode-dialog"):
            yield Label("[Mode Analysis] Signals detected:", id="mode-title")

            for signal_text in self._signals:
                yield Label(f"  * {signal_text}", classes="mode-signal")

            if self._reasoning:
                yield Label(f"\n  LLM: {self._reasoning}", classes="mode-signal")

            compiled_label = "COMPILED — structured batch execution"
            prompt_label = "PROMPT — conversational response"
            if self._recommended == "COMPILED":
                compiled_label += " (recommended)"
            else:
                prompt_label += " (recommended)"

            with RadioSet(id="mode-options"):
                yield RadioButton(compiled_label, value=self._recommended == "COMPILED", id="opt-compiled")
                yield RadioButton(prompt_label, value=self._recommended == "PROMPT", id="opt-prompt")

            with Vertical(classes="mode-buttons"):
                yield Button("Confirm", variant="primary", id="btn-confirm-mode")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-mode":
            self._submit()

    def _submit(self) -> None:
        radio_set = self.query_one("#mode-options", RadioSet)
        if radio_set.pressed_index == 0:
            self.dismiss("COMPILED")
        else:
            self.dismiss("PROMPT")

    def action_cancel(self) -> None:
        self.dismiss(self._recommended)
