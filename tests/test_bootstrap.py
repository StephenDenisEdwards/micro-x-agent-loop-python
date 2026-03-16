"""Tests for bootstrap helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.bootstrap import _load_user_memory


class LoadUserMemoryTests(unittest.TestCase):
    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _load_user_memory(Path(tmp), max_lines=200)
            self.assertEqual("", result)

    def test_loads_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_file = Path(tmp) / "MEMORY.md"
            memory_file.write_text("Line 1\nLine 2\nLine 3", encoding="utf-8")
            result = _load_user_memory(Path(tmp), max_lines=200)
            self.assertEqual("Line 1\nLine 2\nLine 3", result)

    def test_truncates_at_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_file = Path(tmp) / "MEMORY.md"
            memory_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5", encoding="utf-8")
            result = _load_user_memory(Path(tmp), max_lines=3)
            self.assertEqual("Line 1\nLine 2\nLine 3", result)

    def test_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_file = Path(tmp) / "MEMORY.md"
            memory_file.write_text("", encoding="utf-8")
            result = _load_user_memory(Path(tmp), max_lines=200)
            self.assertEqual("", result)


if __name__ == "__main__":
    unittest.main()
