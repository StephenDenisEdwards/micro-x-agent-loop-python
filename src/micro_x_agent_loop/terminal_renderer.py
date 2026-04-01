"""Terminal rendering — markdown and plain-text spinner implementations.

Extracted from ``agent_channel.py`` to give rendering its own module.
"""

from __future__ import annotations

import sys
import threading

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner as RichSpinner
from rich.text import Text

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class RichRenderer:
    """Manages a ``rich.Live`` context that switches between spinner and markdown.

    Lifecycle:
    - ``start_spinner()`` — show a spinner (thinking / tool running)
    - ``switch_to_markdown()`` — transition from spinner to markdown rendering
    - ``append_text(text)`` — buffer text and re-render as markdown
    - ``finalize_text()`` — print the final rendered markdown and reset buffer
    - ``start_spinner(label)`` — switch back to spinner (e.g. next tool call)
    - ``stop()`` — clean up
    """

    def __init__(self, line_prefix: str = "") -> None:
        self._line_prefix = line_prefix
        self._console = Console()
        self._live: Live | None = None
        self._buffer = ""
        self._showing_spinner = False

    def start_spinner(self, label: str = " Thinking...") -> None:
        self._stop_live()
        spinner = RichSpinner("dots", text=Text(label, style="cyan"), style="cyan")
        self._live = Live(
            spinner,
            console=self._console,
            refresh_per_second=10,
            transient=True,
        )
        self._live.start()
        self._showing_spinner = True

    def stop_spinner(self) -> None:
        if self._showing_spinner:
            self._stop_live()
            self._showing_spinner = False

    def is_showing_spinner(self) -> bool:
        return self._showing_spinner

    def switch_to_markdown(self) -> None:
        self._stop_live()
        self._showing_spinner = False
        self._buffer = ""
        self._live = Live(
            Text(""),
            console=self._console,
            refresh_per_second=8,
            transient=True,
            vertical_overflow="visible",
        )
        self._live.start()

    def append_text(self, text: str) -> None:
        self._buffer += text
        if self._live is not None:
            self._live.update(Markdown(self._buffer))

    def finalize_text(self) -> None:
        if not self._buffer:
            return
        self._stop_live()
        self._console.print(Markdown(self._buffer))
        self._buffer = ""

    def print_line(self, text: str) -> None:
        self._console.print(text)

    def stop(self) -> None:
        self._stop_live()
        self._showing_spinner = False
        self._buffer = ""

    def _stop_live(self) -> None:
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None


class PlainSpinner:
    """Thread-based spinner that renders on the current line using \\r."""

    def __init__(self, prefix: str = "", label: str = " Thinking...") -> None:
        self._prefix = prefix
        self._label = label
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_width = 1 + len(label)
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        clear = self._prefix + " " * self._frame_width
        sys.stdout.write("\r" + clear + "\r" + self._prefix)
        sys.stdout.flush()

    def print_line(self, text: str) -> None:
        with self._lock:
            sys.stdout.write(f"\r\033[K{text}\n")
            if not self._stop_event.is_set():
                frame = _SPINNER_FRAMES[0] + self._label
                sys.stdout.write(self._prefix + frame)
            sys.stdout.flush()

    def _run(self) -> None:
        i = 0
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)] + self._label
                    sys.stdout.write("\r" + self._prefix + frame)
                    sys.stdout.flush()
                self._stop_event.wait(0.08)
                i += 1
        except (UnicodeEncodeError, OSError):
            pass
