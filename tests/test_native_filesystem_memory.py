"""Characterization tests for F5 native save_memory. Pins: .md-only
validation, no-traversal rejection, mkdir of memory dir, write, and the
MEMORY.md line-count warning (trailing newline not an extra line).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.native_tools.filesystem.memory_tool import SaveMemoryTool


def _run(coro):
    return asyncio.run(coro)


class SaveMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.mem = os.path.join(os.path.realpath(self._tmp.name), "mem")  # not pre-created
        self.tool = SaveMemoryTool(self.mem, max_lines=5)
        self.addCleanup(self._tmp.cleanup)

    def test_writes_and_creates_dir(self) -> None:
        r = _run(self.tool.execute({"file": "notes.md", "content": "hello"}))
        self.assertFalse(r.is_error)
        self.assertEqual(Path(self.mem, "notes.md").read_text(encoding="utf-8"), "hello")
        self.assertIn("Successfully saved notes.md", r.text)

    def test_rejects_non_md(self) -> None:
        r = _run(self.tool.execute({"file": "notes.txt", "content": "x"}))
        self.assertTrue(r.is_error)
        self.assertIn("Only .md files are allowed", r.text)

    def test_rejects_traversal(self) -> None:
        for bad in ("../evil.md", "sub/notes.md", "a\\b.md", "..md.md/../x.md"):
            r = _run(self.tool.execute({"file": bad, "content": "x"}))
            self.assertTrue(r.is_error, bad)
            self.assertIn("plain filename", r.text)

    def test_memory_md_under_cap_no_warning(self) -> None:
        r = _run(self.tool.execute({"file": "MEMORY.md", "content": "a\nb\nc\n"}))
        self.assertFalse(r.is_error)
        self.assertEqual(r.structured["line_count"], 3)  # trailing \n not counted
        self.assertNotIn("warning", r.structured)

    def test_memory_md_over_cap_warns(self) -> None:
        r = _run(self.tool.execute(
            {"file": "MEMORY.md", "content": "\n".join(f"L{i}" for i in range(20))}
        ))
        self.assertFalse(r.is_error)
        self.assertEqual(r.structured["line_count"], 20)
        self.assertIn("warning", r.structured)
        self.assertIn("only the first 5 lines are loaded", r.text)

    def test_non_index_md_no_line_count(self) -> None:
        r = _run(self.tool.execute({"file": "topic.md", "content": "x\ny\nz"}))
        self.assertNotIn("line_count", r.structured)


if __name__ == "__main__":
    unittest.main()
