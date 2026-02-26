import asyncio
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.bootstrap import _load_user_memory
from micro_x_agent_loop.tools.save_memory_tool import SaveMemoryTool
from tests.fakes import FakeEventEmitter, FakeTool


class LoadUserMemoryTests(unittest.TestCase):
    def test_returns_empty_when_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _load_user_memory(Path(tmp), max_lines=200)
        self.assertEqual(result, "")

    def test_returns_full_content_when_under_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_file = Path(tmp) / "MEMORY.md"
            memory_file.write_text("line1\nline2\nline3", encoding="utf-8")
            result = _load_user_memory(Path(tmp), max_lines=200)
        self.assertEqual(result, "line1\nline2\nline3")

    def test_truncates_at_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_file = Path(tmp) / "MEMORY.md"
            lines = [f"line{i}" for i in range(10)]
            memory_file.write_text("\n".join(lines), encoding="utf-8")
            result = _load_user_memory(Path(tmp), max_lines=3)
        self.assertEqual(result, "line0\nline1\nline2")


class UserMemoryCommandTests(unittest.TestCase):
    def _make_agent(self, *, user_memory_enabled: bool = True, user_memory_dir: str = "") -> Agent:
        return Agent(
            AgentConfig(
                api_key="test",
                tools=[FakeTool()],
                user_memory_enabled=user_memory_enabled,
                user_memory_dir=user_memory_dir,
            )
        )

    def test_memory_shows_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_file = Path(tmp) / "MEMORY.md"
            memory_file.write_text("# My Memory\nHello world", encoding="utf-8")
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory"))
            out = buf.getvalue()
            self.assertIn("# My Memory", out)
            self.assertIn("Hello world", out)

    def test_memory_shows_no_file_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory"))
            self.assertIn("No memory file found", buf.getvalue())

    def test_memory_list_shows_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "MEMORY.md").write_text("index", encoding="utf-8")
            (Path(tmp) / "patterns.md").write_text("patterns", encoding="utf-8")
            (Path(tmp) / "not_md.txt").write_text("ignored", encoding="utf-8")
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory list"))
            out = buf.getvalue()
            self.assertIn("MEMORY.md", out)
            self.assertIn("patterns.md", out)
            self.assertNotIn("not_md.txt", out)

    def test_memory_list_shows_empty_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory list"))
            self.assertIn("No memory files found", buf.getvalue())

    def test_memory_unknown_subcommand_shows_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory bogus"))
            self.assertIn("Usage:", buf.getvalue())

    def test_memory_disabled_shows_message(self) -> None:
        agent = self._make_agent(user_memory_enabled=False, user_memory_dir="")
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/memory"))
        self.assertIn("UserMemoryEnabled=true", buf.getvalue())

    def test_help_includes_memory_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/help"))
            out = buf.getvalue()
            self.assertIn("/memory", out)
            self.assertIn("/memory list", out)
            self.assertIn("/memory edit", out)
            self.assertIn("/memory reset", out)

    def test_help_excludes_memory_when_disabled(self) -> None:
        agent = self._make_agent(user_memory_enabled=False, user_memory_dir="")
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/help"))
        self.assertNotIn("/memory", buf.getvalue())

    def test_memory_edit_no_editor_prints_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with patch.dict("os.environ", {}, clear=True):
                with redirect_stdout(buf):
                    asyncio.run(agent._handle_local_command("/memory edit"))
            out = buf.getvalue()
            self.assertIn("No $EDITOR set", out)
            self.assertIn("MEMORY.md", out)

    def test_memory_reset_asks_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "MEMORY.md").write_text("content", encoding="utf-8")
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory reset"))
            out = buf.getvalue()
            self.assertIn("1 memory file(s)", out)
            self.assertIn("reset confirm", out)
            # File should still exist
            self.assertTrue((Path(tmp) / "MEMORY.md").exists())

    def test_memory_reset_confirm_deletes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "MEMORY.md").write_text("content", encoding="utf-8")
            (Path(tmp) / "notes.md").write_text("notes", encoding="utf-8")
            (Path(tmp) / "keep.txt").write_text("kept", encoding="utf-8")
            agent = self._make_agent(user_memory_dir=tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory reset confirm"))
            out = buf.getvalue()
            self.assertIn("Deleted 2 memory file(s)", out)
            # .md files gone, .txt kept
            self.assertFalse((Path(tmp) / "MEMORY.md").exists())
            self.assertFalse((Path(tmp) / "notes.md").exists())
            self.assertTrue((Path(tmp) / "keep.txt").exists())

    def test_memory_reset_no_dir_shows_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nonexistent")
            agent = self._make_agent(user_memory_dir=missing)
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent._handle_local_command("/memory reset"))
            self.assertIn("No memory directory to reset", buf.getvalue())


class SaveMemoryToolTests(unittest.TestCase):
    def test_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            result = asyncio.run(tool.execute({"file": "MEMORY.md", "content": "hello"}))
            self.assertIn("Successfully saved", result)
            self.assertEqual((Path(tmp) / "MEMORY.md").read_text(encoding="utf-8"), "hello")

    def test_creates_topic_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            result = asyncio.run(tool.execute({"file": "patterns.md", "content": "# Patterns"}))
            self.assertIn("Successfully saved", result)
            self.assertTrue((Path(tmp) / "patterns.md").exists())

    def test_rejects_non_md_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            result = asyncio.run(tool.execute({"file": "secrets.txt", "content": "bad"}))
            self.assertIn("Error", result)
            self.assertIn(".md", result)

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            result = asyncio.run(tool.execute({"file": "../escape.md", "content": "bad"}))
            self.assertIn("Error", result)
            self.assertIn("path separator", result)

    def test_rejects_path_with_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            result = asyncio.run(tool.execute({"file": "sub/file.md", "content": "bad"}))
            self.assertIn("Error", result)

    def test_warns_when_memory_exceeds_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp, max_lines=5)
            content = "\n".join(f"line{i}" for i in range(10))
            result = asyncio.run(tool.execute({"file": "MEMORY.md", "content": content}))
            self.assertIn("Warning", result)
            self.assertIn("10 lines", result)
            self.assertIn("5", result)

    def test_no_warning_when_under_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp, max_lines=200)
            result = asyncio.run(tool.execute({"file": "MEMORY.md", "content": "short"}))
            self.assertIn("Successfully saved", result)
            self.assertNotIn("Warning", result)

    def test_no_warning_for_non_memory_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp, max_lines=1)
            content = "\n".join(f"line{i}" for i in range(10))
            result = asyncio.run(tool.execute({"file": "other.md", "content": content}))
            self.assertNotIn("Warning", result)

    def test_creates_memory_dir_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = str(Path(tmp) / "nested" / "memory")
            tool = SaveMemoryTool(memory_dir)
            result = asyncio.run(tool.execute({"file": "MEMORY.md", "content": "hello"}))
            self.assertIn("Successfully saved", result)
            self.assertTrue((Path(memory_dir) / "MEMORY.md").exists())

    def test_rejects_empty_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            result = asyncio.run(tool.execute({"file": "", "content": "bad"}))
            self.assertIn("Error", result)

    def test_tool_properties(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = SaveMemoryTool(tmp)
            self.assertEqual(tool.name, "save_memory")
            self.assertFalse(tool.is_mutating)
            self.assertEqual(tool.predict_touched_paths({}), [])
            self.assertIn("save_memory", tool.name)
            self.assertIn("file", tool.input_schema["properties"])
            self.assertIn("content", tool.input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
