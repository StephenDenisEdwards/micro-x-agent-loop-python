"""Tests for the filesystem-root surfacing in the system prompt — ensures the
model is told about FILESYSTEM_ALLOWED_DIRS / FILESYSTEM_READONLY_DIRS so it
won't refuse a request just because a path is outside its working directory.
"""

from __future__ import annotations

import os
import unittest

from micro_x_agent_loop.system_prompt import (
    filesystem_roots_from_config,
    get_system_prompt,
)


class FilesystemRootsFromConfigTests(unittest.TestCase):
    def test_empty_config_returns_empty_lists(self) -> None:
        extra, ro = filesystem_roots_from_config({})
        self.assertEqual([], extra)
        self.assertEqual([], ro)

    def test_non_dict(self) -> None:
        extra, ro = filesystem_roots_from_config(None)
        self.assertEqual([], extra)
        self.assertEqual([], ro)

    def test_missing_keys(self) -> None:
        extra, ro = filesystem_roots_from_config({"WorkingDir": "C:\\wd"})
        self.assertEqual([], extra)
        self.assertEqual([], ro)

    def test_parses_split_by_pathsep(self) -> None:
        # Use platform-agnostic paths that do not collide with os.pathsep
        # (which is ":" on POSIX and ";" on Windows).
        a, b, c = "/path/one", "/path/two", "/path/three"
        cfg = {
            "AllowedDirs": os.pathsep.join([a, b]),
            "ReadonlyDirs": c,
        }
        extra, ro = filesystem_roots_from_config(cfg)
        self.assertEqual([a, b], extra)
        self.assertEqual([c], ro)

    def test_skips_blank_entries(self) -> None:
        real = "/path/real"
        cfg = {"AllowedDirs": os.pathsep.join([real, "", "  "])}
        extra, _ = filesystem_roots_from_config(cfg)
        self.assertEqual([real], extra)


class SystemPromptFilesystemSectionTests(unittest.TestCase):
    def test_no_roots_no_section(self) -> None:
        prompt = get_system_prompt(working_directory="/wd")
        self.assertNotIn("additional roots", prompt)
        self.assertIn("Your working directory is: /wd", prompt)

    def test_extra_allowed_dirs_rendered(self) -> None:
        prompt = get_system_prompt(
            working_directory="/wd",
            extra_allowed_dirs=["/repo/tools"],
        )
        self.assertIn("/repo/tools (read/write)", prompt)
        self.assertIn("Do not refuse a request just because a path is outside", prompt)

    def test_readonly_dirs_rendered_with_warning(self) -> None:
        prompt = get_system_prompt(
            working_directory="/wd",
            readonly_dirs=["/repo/tools/_runtime"],
        )
        self.assertIn("/repo/tools/_runtime (read-only", prompt)
        self.assertIn("write_file, append_file, edit_file, delete_file will be rejected", prompt)

    def test_both_sections_rendered(self) -> None:
        prompt = get_system_prompt(
            working_directory="/wd",
            extra_allowed_dirs=["/repo/tools"],
            readonly_dirs=["/repo/tools/_runtime"],
        )
        self.assertIn("/repo/tools (read/write)", prompt)
        self.assertIn("/repo/tools/_runtime (read-only", prompt)


if __name__ == "__main__":
    unittest.main()
