"""ESC key watcher for interrupting asyncio tasks from a background thread.

Uses Windows Console API (ReadConsoleInput) to read keyboard events directly,
avoiding conflicts with Python's input() which uses a separate read path.
"""

from __future__ import annotations

import asyncio
import threading


class EscWatcher:
    """Watches for ESC keypress in a background thread to cancel an asyncio task."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._available = False
        try:
            import ctypes

            self._kernel32 = ctypes.windll.kernel32
            self._available = True
        except (ImportError, AttributeError, OSError):
            pass

    def start(self, task: asyncio.Task, loop: asyncio.AbstractEventLoop) -> None:
        if not self._available:
            return
        self._task = task
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._task = None
        self._loop = None

    def shutdown(self) -> None:
        self.stop()

    def _poll(self) -> None:
        import ctypes
        import ctypes.wintypes as wt

        STD_INPUT_HANDLE = -10
        KEY_EVENT = 0x0001
        VK_ESCAPE = 0x1B

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("bKeyDown", wt.BOOL),
                ("wRepeatCount", wt.WORD),
                ("wVirtualKeyCode", wt.WORD),
                ("wVirtualScanCode", wt.WORD),
                ("uChar", wt.WCHAR),
                ("dwControlKeyState", wt.DWORD),
            ]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [
                ("EventType", wt.WORD),
                ("_padding", wt.WORD),
                ("Event", KEY_EVENT_RECORD),
            ]

        kernel32 = self._kernel32
        h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)

        rec = INPUT_RECORD()
        read_count = wt.DWORD(0)

        while not self._stop_event.is_set():
            result = kernel32.WaitForSingleObject(h_stdin, 100)
            if result != 0:  # WAIT_OBJECT_0
                continue

            avail = wt.DWORD(0)
            kernel32.GetNumberOfConsoleInputEvents(h_stdin, ctypes.byref(avail))
            if avail.value == 0:
                continue

            success = kernel32.PeekConsoleInputW(h_stdin, ctypes.byref(rec), 1, ctypes.byref(read_count))
            if not success or read_count.value == 0:
                continue

            if rec.EventType == KEY_EVENT and rec.Event.bKeyDown and rec.Event.wVirtualKeyCode == VK_ESCAPE:
                kernel32.ReadConsoleInputW(h_stdin, ctypes.byref(rec), 1, ctypes.byref(read_count))
                task = self._task
                loop = self._loop
                if task is not None and loop is not None and not task.done():
                    loop.call_soon_threadsafe(task.cancel)
                return

            if rec.EventType != KEY_EVENT:
                kernel32.ReadConsoleInputW(h_stdin, ctypes.byref(rec), 1, ctypes.byref(read_count))
            else:
                self._stop_event.wait(0.1)
