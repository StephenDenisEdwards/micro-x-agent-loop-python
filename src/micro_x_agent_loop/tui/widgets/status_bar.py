"""StatusBar widget — footer showing cost, tokens, session info."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

if TYPE_CHECKING:
    from micro_x_agent_loop.metrics import SessionAccumulator


class StatusBar(Static):
    """Footer widget displaying session metrics."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self, accumulator: SessionAccumulator, budget_usd: float = 0.0, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__("", id=id)
        self._accumulator = accumulator
        self._budget_usd = budget_usd

    def refresh_metrics(self) -> None:
        """Re-render the status text from the accumulator."""
        text = self._accumulator.format_toolbar(budget_usd=self._budget_usd)
        self.update(f" {text}")
