"""TaskPanel widget — right sidebar showing task decomposition progress."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from micro_x_agent_loop.tasks.models import Task, TaskStatus

_MAX_VISIBLE_TASKS = 10

_STATUS_ICON = {
    TaskStatus.PENDING: "[dim]○[/dim]",
    TaskStatus.IN_PROGRESS: "[yellow]●[/yellow]",
    TaskStatus.COMPLETED: "[green]✓[/green]",
}


class _TaskEntry(Static):
    """A single task line in the panel."""

    DEFAULT_CSS = """
    _TaskEntry {
        height: auto;
        padding: 0 1;
    }
    """


class TaskPanel(VerticalScroll):
    """Scrollable panel showing the current task list with status, owner, and blockers.

    Display rules (guide Section 10.2):
    - Max 10 tasks shown
    - Internal tasks (metadata._internal) hidden
    - Completed blockers filtered from blockedBy display
    - Color-coded by status
    """

    DEFAULT_CSS = """
    TaskPanel {
        width: 30;
        height: 1fr;
        border-left: solid $primary;
        scrollbar-size-vertical: 1;
        display: none;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._tasks: list[Task] = []

    def update_tasks(self, tasks: list[Task]) -> None:
        """Replace the task list with a fresh snapshot and re-render."""
        # Filter internal tasks
        visible = [t for t in tasks if not (t.metadata and t.metadata.get("_internal"))]
        self._tasks = visible[:_MAX_VISIBLE_TASKS]
        self._render_tasks()

        # Auto-show when there are tasks, auto-hide when empty
        if self._tasks:
            self.display = True
        # Don't auto-hide here — that's handled by the auto-hide timer in the app

    def set_visible(self, visible: bool) -> None:
        """Explicitly show or hide the panel."""
        self.display = visible

    def _render_tasks(self) -> None:
        """Clear and re-render all task entries."""
        for entry in self.query(_TaskEntry):
            entry.remove()

        if not self._tasks:
            return

        # Build set of completed IDs for blocker filtering
        completed_ids = {t.id for t in self._tasks if t.status == TaskStatus.COMPLETED}

        for task in self._tasks:
            icon = _STATUS_ICON.get(task.status, "?")
            line = f"{icon} [bold]#{task.id}[/bold] {escape(task.subject)}"
            if task.owner:
                line += f" [dim]({escape(task.owner)})[/dim]"
            # Show only active blockers
            active_blockers = [bid for bid in task.blocked_by if bid not in completed_ids]
            if active_blockers:
                refs = ", ".join(f"#{bid}" for bid in active_blockers)
                line += f" [red][blocked by {refs}][/red]"
            self.mount(_TaskEntry(line))

        self.scroll_end(animate=False)

    def compose(self) -> ComposeResult:
        yield Static("[bold]Tasks[/bold]", classes="task-panel-title")
