import sys
import threading

from loguru import logger

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


_active_spinner: "Spinner | None" = None


class Spinner:
    """Thread-based spinner that renders on the current line using \\r."""

    def __init__(self, prefix: str = "", label: str = " Thinking..."):
        self._prefix = prefix
        self._label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_width = 1 + len(label)
        self._lock = threading.Lock()

    def start(self) -> None:
        global _active_spinner
        _active_spinner = self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        global _active_spinner
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread:
            self._thread.join()
        _active_spinner = None
        # Clear spinner text: overwrite with spaces, then reposition cursor after prefix
        clear = self._prefix + " " * self._frame_width
        sys.stdout.write("\r" + clear + "\r" + self._prefix)
        sys.stdout.flush()

    def print_line(self, text: str) -> None:
        """Print a line while the spinner is active, without visual collision."""
        with self._lock:
            sys.stdout.write(f"\r\033[K{text}\n")
            # Redraw spinner immediately so it appears below the message
            if not self._stop.is_set():
                frame = _SPINNER_FRAMES[0] + self._label
                sys.stdout.write(self._prefix + frame)
            sys.stdout.flush()

    def _run(self) -> None:
        i = 0
        try:
            while not self._stop.is_set():
                with self._lock:
                    frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)] + self._label
                    sys.stdout.write("\r" + self._prefix + frame)
                    sys.stdout.flush()
                self._stop.wait(0.08)
                i += 1
        except (UnicodeEncodeError, OSError):
            pass  # Terminal doesn't support these characters; fail silently


def print_through_spinner(text: str) -> None:
    """Print a line, clearing any active spinner first. Safe to call without a spinner."""
    spinner = _active_spinner
    if spinner is not None:
        spinner.print_line(text)
    else:
        print(text, flush=True)


def _on_retry(retry_state):
    attempt = retry_state.attempt_number
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    reason = type(exc).__name__ if exc else "Unknown"
    logger.warning(f"{reason}. Retrying in {wait:.0f}s (attempt {attempt}/5)...")
