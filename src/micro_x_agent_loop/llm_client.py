import sys
import threading

from loguru import logger

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """Thread-based spinner that renders on the current line using \\r."""

    def __init__(self, prefix: str = "", label: str = " Thinking..."):
        self._prefix = prefix
        self._label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_width = 1 + len(label)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread:
            self._thread.join()
        # Clear spinner text: overwrite with spaces, then reposition cursor after prefix
        clear = self._prefix + " " * self._frame_width
        sys.stdout.write("\r" + clear + "\r" + self._prefix)
        sys.stdout.flush()

    def _run(self) -> None:
        i = 0
        try:
            while not self._stop.is_set():
                frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)] + self._label
                sys.stdout.write("\r" + self._prefix + frame)
                sys.stdout.flush()
                self._stop.wait(0.08)
                i += 1
        except (UnicodeEncodeError, OSError):
            pass  # Terminal doesn't support these characters; fail silently


def _on_retry(retry_state):
    attempt = retry_state.attempt_number
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    reason = type(exc).__name__ if exc else "Unknown"
    logger.warning(f"{reason}. Retrying in {wait:.0f}s (attempt {attempt}/5)...")
