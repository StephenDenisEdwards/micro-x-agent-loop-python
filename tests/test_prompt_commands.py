"""Tests for PromptCommandStore."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore


class PromptCommandStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_commands_no_dir(self) -> None:
        store = PromptCommandStore(self._dir / "nonexistent")
        result = store.list_commands()
        self.assertEqual([], result)

    def test_list_commands_empty_dir(self) -> None:
        store = PromptCommandStore(self._dir)
        result = store.list_commands()
        self.assertEqual([], result)

    def test_list_commands_returns_md_files(self) -> None:
        (self._dir / "greet.md").write_text("Say hello to the user\n\nHello!")
        (self._dir / "summarize.md").write_text("Summarise the conversation")
        store = PromptCommandStore(self._dir)
        result = store.list_commands()
        names = [name for name, _ in result]
        self.assertIn("greet", names)
        self.assertIn("summarize", names)

    def test_list_commands_ignores_non_md(self) -> None:
        (self._dir / "greet.md").write_text("Hello")
        (self._dir / "readme.txt").write_text("ignore me")
        store = PromptCommandStore(self._dir)
        result = store.list_commands()
        names = [name for name, _ in result]
        self.assertIn("greet", names)
        self.assertNotIn("readme", names)

    def test_list_commands_description_is_first_line(self) -> None:
        (self._dir / "cmd.md").write_text("First line description\nSecond line")
        store = PromptCommandStore(self._dir)
        result = store.list_commands()
        self.assertEqual(1, len(result))
        name, desc = result[0]
        self.assertEqual("cmd", name)
        self.assertEqual("First line description", desc)

    def test_list_commands_empty_file_shows_no_description(self) -> None:
        (self._dir / "empty.md").write_text("")
        store = PromptCommandStore(self._dir)
        result = store.list_commands()
        _, desc = result[0]
        self.assertEqual("(no description)", desc)

    def test_list_commands_sorted(self) -> None:
        (self._dir / "zzz.md").write_text("last")
        (self._dir / "aaa.md").write_text("first")
        store = PromptCommandStore(self._dir)
        result = store.list_commands()
        names = [name for name, _ in result]
        self.assertEqual(["aaa", "zzz"], names)

    def test_load_command_found(self) -> None:
        content = "Full prompt text\n\nWith multiple lines."
        (self._dir / "myprompt.md").write_text(content)
        store = PromptCommandStore(self._dir)
        result = store.load_command("myprompt")
        self.assertEqual(content, result)

    def test_load_command_not_found(self) -> None:
        store = PromptCommandStore(self._dir)
        result = store.load_command("nonexistent")
        self.assertIsNone(result)

    def test_load_command_directory_not_dir(self) -> None:
        store = PromptCommandStore(self._dir / "missing")
        result = store.load_command("anything")
        self.assertIsNone(result)

    def test_read_first_line_unreadable_returns_fallback(self) -> None:
        """_read_first_line should return '(unreadable)' on OSError."""
        store = PromptCommandStore(self._dir)
        # Simulate by passing a non-existent path directly
        result = store._read_first_line(self._dir / "ghost.md")
        self.assertEqual("(unreadable)", result)


if __name__ == "__main__":
    unittest.main()
