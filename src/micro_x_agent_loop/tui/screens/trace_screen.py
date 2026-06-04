"""TraceScreen — full-screen session step-through browser (PLAN-observability Phase 2 TUI).

A read-only navigator over persisted sessions: a lazy tree (sessions → turns →
events) on the left, and a Markdown detail panel on the right that formats the
selected event appropriately (prose as Markdown, verbatim messages/tool schemas
as fenced JSON, metrics as key/value). Entered from the live TUI and dismissed
with Escape — it never touches the active conversation.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, Tree
from textual.widgets.tree import TreeNode

from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.session_replay import build_session_model

_WELCOME = (
    "# Session trace\n\n"
    "Select an event in the tree to see exactly what happened — "
    "including the verbatim request when captured.\n\n"
    "_Esc to return to chat._"
)


class TraceScreen(ModalScreen[None]):
    """Tree + detail browser over `memory.db` sessions."""

    CSS = """
    TraceScreen { align: center middle; }
    #trace-root { width: 100%; height: 100%; background: $surface; }
    #trace-title { dock: top; height: 1; background: $primary; color: $text; padding: 0 1; }
    #trace-body { height: 1fr; }
    #trace-tree { width: 45%; border-right: solid $primary; }
    #trace-detail-scroll { width: 1fr; padding: 0 1; }
    #trace-hint { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Back to chat", show=True),
    ]

    def __init__(
        self,
        store: MemoryStore,
        sessions: list[tuple[str, str]],
        *,
        focus_session_id: str | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._sessions = sessions
        self._focus_session_id = focus_session_id

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="trace-root"):
            yield Label("Session Trace — step-through", id="trace-title")
            with Horizontal(id="trace-body"):
                tree: Tree[dict] = Tree("Sessions", id="trace-tree")
                tree.root.expand()
                yield tree
                with VerticalScroll(id="trace-detail-scroll"):
                    yield Markdown(_WELCOME, id="trace-detail")
            yield Label("↑/↓ navigate · Enter/→ expand · Esc back to chat", id="trace-hint")

    def on_mount(self) -> None:
        tree = self.query_one("#trace-tree", Tree)
        focus_node: TreeNode[dict] | None = None
        for sid, title in self._sessions:
            label = f"{title or '(untitled)'}  ·  {sid[:8]}"
            node = tree.root.add(label, data={"type": "session", "sid": sid, "loaded": False})
            if sid == self._focus_session_id:
                focus_node = node
        if focus_node is not None:
            focus_node.expand()  # triggers lazy population via on_tree_node_expanded

    # -- lazy population ----------------------------------------------------

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[dict]) -> None:
        data = event.node.data or {}
        if data.get("type") == "session" and not data.get("loaded"):
            data["loaded"] = True
            self._populate_session(event.node, data["sid"])

    def _populate_session(self, node: TreeNode[dict], session_id: str) -> None:
        try:
            model = build_session_model(self._store, session_id)
        except ValueError:
            node.add_leaf("(no persisted trace)", data={"type": "info"})
            return
        for turn in model.turns:
            turn_node = node.add(turn.label, data={"type": "turn"})
            for ev in turn.events:
                turn_node.add_leaf(ev.label, data={"type": "event", "detail": ev.detail_md})
            turn_node.expand()

    # -- selection ----------------------------------------------------------

    def on_tree_node_selected(self, event: Tree.NodeSelected[dict]) -> None:
        data: dict[str, Any] = event.node.data or {}
        if data.get("type") == "event":
            self.query_one("#trace-detail", Markdown).update(data.get("detail", ""))

    def action_close(self) -> None:
        self.dismiss(None)
