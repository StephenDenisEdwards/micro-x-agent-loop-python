"""Characterization tests for the native PathPolicy (ADR-025 filesystem F1).

This is the security boundary for every native filesystem tool, and there
was no TS test suite to port — so these pin the behaviour explicitly:
containment, relative resolution, symlink-escape defense, readonly
enforcement, must_exist semantics, and the exact error-message strings.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.native_tools.filesystem.paths import (
    PathPolicy,
    PathPolicyError,
    is_path_allowed,
    load_path_policy,
    require_writable,
    resolve_allowed,
)


class LoadPathPolicyTests(unittest.TestCase):
    def test_parses_list_trims_and_abspaths(self) -> None:
        env = f" a {os.pathsep}{os.pathsep} b "
        pol = load_path_policy(os.getcwd(), env, None)
        self.assertEqual(pol.working_dir, os.path.abspath(os.getcwd()))
        self.assertEqual(
            pol.extra_allowed, [os.path.abspath("a"), os.path.abspath("b")]
        )
        self.assertEqual(pol.readonly, [])

    def test_none_envs_yield_empty(self) -> None:
        pol = load_path_policy(os.getcwd(), None, None)
        self.assertEqual(pol.extra_allowed, [])
        self.assertEqual(pol.readonly, [])


class ResolveAllowedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.policy = PathPolicy(working_dir=self.root, extra_allowed=[], readonly=[])
        (Path(self.root) / "f.txt").write_text("hi", encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_existing_file_inside_working_dir(self) -> None:
        out = resolve_allowed(self.policy, "f.txt")
        self.assertEqual(out, os.path.join(self.root, "f.txt"))

    def test_absolute_inside_extra_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            other_real = os.path.realpath(other)
            (Path(other_real) / "g.txt").write_text("x", encoding="utf-8")
            pol = PathPolicy(self.root, extra_allowed=[other_real], readonly=[])
            out = resolve_allowed(pol, os.path.join(other_real, "g.txt"))
            self.assertEqual(out, os.path.join(other_real, "g.txt"))

    def test_outside_all_roots_raises_with_message(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            target = os.path.join(os.path.realpath(outside), "nope.txt")
            Path(target).write_text("x", encoding="utf-8")
            with self.assertRaises(PathPolicyError) as ctx:
                resolve_allowed(self.policy, target)
            self.assertIn("is outside the allowed roots", str(ctx.exception))
            self.assertIn("FILESYSTEM_ALLOWED_DIRS", str(ctx.exception))

    def test_missing_path_must_exist_true_raises_oserror(self) -> None:
        # Faithful to Node fs.realpath throwing ENOENT (not a PathPolicyError).
        with self.assertRaises(OSError):
            resolve_allowed(self.policy, "does-not-exist.txt", must_exist=True)

    def test_missing_path_must_exist_false_ok_when_under_root(self) -> None:
        out = resolve_allowed(self.policy, "sub/dir/new.txt", must_exist=False)
        self.assertTrue(out.startswith(self.root))

    def test_symlink_escape_is_rejected(self) -> None:
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        secret = Path(os.path.realpath(outside)) / "secret.txt"
        secret.write_text("top", encoding="utf-8")
        link = Path(self.root) / "escape"
        try:
            os.symlink(os.path.realpath(outside), link, target_is_directory=True)
        except (OSError, NotImplementedError) as ex:
            self.skipTest(f"symlink unsupported / unprivileged: {ex}")
        with self.assertRaises(PathPolicyError):
            resolve_allowed(self.policy, "escape/secret.txt")


class RequireWritableTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.ro = os.path.join(self.root, "ro")
        os.makedirs(self.ro)
        self.policy = PathPolicy(self.root, extra_allowed=[], readonly=[self.ro])
        self.addCleanup(self._tmp.cleanup)

    def test_empty_readonly_never_raises(self) -> None:
        require_writable(PathPolicy(self.root), os.path.join(self.root, "x"))

    def test_inside_readonly_raises_with_message(self) -> None:
        with self.assertRaises(PathPolicyError) as ctx:
            require_writable(self.policy, os.path.join(self.ro, "x.txt"))
        self.assertIn("read-only root", str(ctx.exception))

    def test_outside_readonly_ok(self) -> None:
        require_writable(self.policy, os.path.join(self.root, "writable.txt"))

    def test_readonly_dir_is_still_resolvable(self) -> None:
        # readonly roots are allowed for reads (in the roots list) but
        # require_writable still blocks mutation.
        (Path(self.ro) / "r.txt").write_text("x", encoding="utf-8")
        out = resolve_allowed(self.policy, os.path.join(self.ro, "r.txt"))
        self.assertEqual(out, os.path.join(self.ro, "r.txt"))
        with self.assertRaises(PathPolicyError):
            require_writable(self.policy, out)


class IsPathAllowedTests(unittest.TestCase):
    def test_true_and_false(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            pol = PathPolicy(os.path.realpath(root))
            self.assertTrue(is_path_allowed(pol, "anything/under/root.txt"))
            self.assertFalse(
                is_path_allowed(pol, os.path.join(os.path.realpath(outside), "x"))
            )


if __name__ == "__main__":
    unittest.main()
