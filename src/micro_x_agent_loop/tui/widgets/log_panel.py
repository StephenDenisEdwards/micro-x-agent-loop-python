"""LogPanel widget — toggleable panel showing live log events."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from textual.widgets import RichLog

# Map loguru levels to Rich markup styles
_LEVEL_STYLES: dict[str, str] = {
    "TRACE": "dim",
    "DEBUG": "dim cyan",
    "INFO": "green",
    "SUCCESS": "bold green",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold white on red",
}


class LogPanel(RichLog):
    """RichLog-based panel showing log entries from loguru.

    Log messages are buffered in a thread-safe deque and flushed
    by a Textual timer.  ``RichLog.write()`` is much cheaper than
    mounting individual ``Static`` widgets.
    """

    DEFAULT_CSS = """
    LogPanel {
        height: 12;
        border-top: solid $primary;
        scrollbar-size-vertical: 1;
        display: none;
    }
    """

    def __init__(self, *, id: str | None = None, max_lines: int = 500) -> None:  # noqa: A002
        super().__init__(id=id, max_lines=max_lines, wrap=True, markup=True)
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def on_mount(self) -> None:
        """Start a timer to flush buffered log entries."""
        self.write("[bold]Logs[/bold]  (Ctrl+L to hide)")
        self.set_interval(0.5, self._flush_buffer)

    def _flush_buffer(self) -> None:
        """Write buffered entries to the RichLog."""
        with self._lock:
            entries = list(self._buffer)
            self._buffer.clear()

        for line in entries:
            self.write(line)

    def sink(self, message: Any) -> None:
        """Loguru sink — buffers the formatted log line.

        Called synchronously by loguru from any thread.
        Only touches the thread-safe deque — no DOM operations.
        """
        record = message.record
        level = record["level"].name
        text = str(record["message"]).rstrip()
        module = record.get("name", "")
        func = record.get("function", "")
        if module and func:
            prefix = f"{module}:{func} - "
        elif module:
            prefix = f"{module} - "
        else:
            prefix = ""

        style = _LEVEL_STYLES.get(level, "")
        if style:
            line = f"[{style}]{level:<8}[/{style}] {prefix}{text}"
        else:
            line = f"{level:<8} {prefix}{text}"

        with self._lock:
            self._buffer.append(line)
