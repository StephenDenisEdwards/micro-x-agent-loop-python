"""Characterization tests for F3 native mutating filesystem tools
(write/append/edit/delete). Pins faithful behaviour: readonly-root
rejection, parent-dir creation, append missing-file message, delete
directory refusal, edit_file uniqueness / EOL-normalise / BOM / size /
binary guards. No TS suite existed to port.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.native_tools.filesystem.paths import PathPolicy
from micro_x_agent_loop.native_tools.filesystem.write_tools import (
    AppendFileTool,
    DeleteFileTool,
    EditFileTool,
    WriteFileTool,
)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.ro = os.path.join(self.root, "ro")
        os.makedirs(self.ro)
        self.policy = PathPolicy(self.root, extra_allowed=[], readonly=[self.ro])
        self.addCleanup(self._tmp.cleanup)


class WriteFileTests(_Base):
    async def test_creates_with_parents(self) -> None:
        t = WriteFileTool(self.policy)
        r = await t.execute({"path": "a/b/c.txt", "content": "héllo"})
        self.assertFalse(r.is_error)
        self.assertTrue(t.is_mutating)
        self.assertEqual(
            Path(self.root, "a", "b", "c.txt").read_text(encoding="utf-8"), "héllo"
        )
        self.assertEqual(r.structured["size_bytes"], len("héllo".encode()))

    async def test_readonly_rejected(self) -> None:
        r = await WriteFileTool(self.policy).execute(
            {"path": "ro/x.txt", "content": "no"}
        )
        self.assertTrue(r.is_error)
        self.assertIn("read-only root", r.text)

    async def test_outside_roots_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            r = await WriteFileTool(self.policy).execute(
                {"path": os.path.join(os.path.realpath(out), "x"), "content": "n"}
            )
            self.assertTrue(r.is_error)
            self.assertIn("outside the allowed roots", r.text)


class AppendFileTests(_Base):
    async def test_append_existing(self) -> None:
        (Path(self.root) / "f.txt").write_text("a", encoding="utf-8")
        r = await AppendFileTool(self.policy).execute({"path": "f.txt", "content": "b"})
        self.assertFalse(r.is_error)
        self.assertEqual(Path(self.root, "f.txt").read_text(encoding="utf-8"), "ab")

    async def test_missing_file_friendly_error(self) -> None:
        r = await AppendFileTool(self.policy).execute({"path": "no.txt", "content": "b"})
        self.assertTrue(r.is_error)
        self.assertIn("Use write_file to create it first", r.text)

    async def test_readonly_rejected(self) -> None:
        (Path(self.ro) / "f.txt").write_text("a", encoding="utf-8")
        r = await AppendFileTool(self.policy).execute({"path": "ro/f.txt", "content": "b"})
        self.assertTrue(r.is_error)
        self.assertIn("read-only root", r.text)


class DeleteFileTests(_Base):
    async def test_delete(self) -> None:
        p = Path(self.root) / "d.txt"
        p.write_text("xyz", encoding="utf-8")
        r = await DeleteFileTool(self.policy).execute({"path": "d.txt"})
        self.assertFalse(r.is_error)
        self.assertFalse(p.exists())
        self.assertEqual(r.structured["size_bytes"], 3)

    async def test_refuses_directory(self) -> None:
        os.makedirs(os.path.join(self.root, "adir"))
        r = await DeleteFileTool(self.policy).execute({"path": "adir"})
        self.assertTrue(r.is_error)
        self.assertIn("refusing to delete directory", r.text)

    async def test_not_found(self) -> None:
        r = await DeleteFileTool(self.policy).execute({"path": "nope"})
        self.assertTrue(r.is_error)
        self.assertIn("file not found", r.text)

    async def test_readonly_rejected(self) -> None:
        (Path(self.ro) / "f.txt").write_text("a", encoding="utf-8")
        r = await DeleteFileTool(self.policy).execute({"path": "ro/f.txt"})
        self.assertTrue(r.is_error)
        self.assertIn("read-only root", r.text)


class EditFileTests(_Base):
    def _write(self, name: str, text: str) -> None:
        (Path(self.root) / name).write_text(text, encoding="utf-8", newline="")

    async def test_unique_replace(self) -> None:
        self._write("e.txt", "alpha BETA gamma")
        r = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "BETA", "new_string": "DELTA"}
        )
        self.assertFalse(r.is_error)
        self.assertEqual(r.structured["replacements"], 1)
        self.assertEqual(
            Path(self.root, "e.txt").read_text(encoding="utf-8"), "alpha DELTA gamma"
        )

    async def test_not_unique_without_replace_all(self) -> None:
        self._write("e.txt", "x x x")
        r = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "x", "new_string": "y"}
        )
        self.assertTrue(r.is_error)
        self.assertIn("not unique (3 matches)", r.text)

    async def test_replace_all(self) -> None:
        self._write("e.txt", "x x x")
        r = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "x", "new_string": "y", "replace_all": True}
        )
        self.assertEqual(r.structured["replacements"], 3)
        self.assertEqual(Path(self.root, "e.txt").read_text(encoding="utf-8"), "y y y")

    async def test_not_found_string(self) -> None:
        self._write("e.txt", "abc")
        r = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "zzz", "new_string": "q"}
        )
        self.assertTrue(r.is_error)
        self.assertIn("old_string not found", r.text)

    async def test_empty_old_and_noop(self) -> None:
        self._write("e.txt", "abc")
        r1 = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "", "new_string": "q"}
        )
        self.assertIn("old_string is empty", r1.text)
        r2 = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "a", "new_string": "a"}
        )
        self.assertIn("identical — refusing no-op", r2.text)

    async def test_crlf_normalisation(self) -> None:
        # File uses CRLF; old_string given with LF must still match.
        self._write("e.txt", "line1\r\nTARGET\r\nline3\r\n")
        r = await EditFileTool(self.policy).execute(
            {"path": "e.txt", "old_string": "TARGET\n", "new_string": "REPL\n"}
        )
        self.assertFalse(r.is_error)
        data = Path(self.root, "e.txt").read_bytes()
        self.assertIn(b"REPL\r\n", data)  # written back as CRLF

    async def test_bom_preserved(self) -> None:
        p = Path(self.root) / "b.txt"
        p.write_bytes(b"\xef\xbb\xbfhello world")
        r = await EditFileTool(self.policy).execute(
            {"path": "b.txt", "old_string": "world", "new_string": "there"}
        )
        self.assertFalse(r.is_error)
        self.assertEqual(p.read_bytes(), b"\xef\xbb\xbfhello there")

    async def test_binary_refused(self) -> None:
        (Path(self.root) / "bin").write_bytes(b"a\x00b")
        r = await EditFileTool(self.policy).execute(
            {"path": "bin", "old_string": "a", "new_string": "c"}
        )
        self.assertTrue(r.is_error)
        self.assertIn("refusing to edit binary file", r.text)

    async def test_size_limit(self) -> None:
        os.environ["FILESYSTEM_EDIT_MAX_BYTES"] = "8"
        self.addCleanup(os.environ.pop, "FILESYSTEM_EDIT_MAX_BYTES", None)
        self._write("big.txt", "0123456789")
        r = await EditFileTool(self.policy).execute(
            {"path": "big.txt", "old_string": "0", "new_string": "x"}
        )
        self.assertTrue(r.is_error)
        self.assertIn("file too large for edit_file", r.text)

    async def test_readonly_rejected(self) -> None:
        (Path(self.ro) / "e.txt").write_text("abc", encoding="utf-8")
        r = await EditFileTool(self.policy).execute(
            {"path": "ro/e.txt", "old_string": "abc", "new_string": "d"}
        )
        self.assertTrue(r.is_error)
        self.assertIn("read-only root", r.text)


if __name__ == "__main__":
    unittest.main()
