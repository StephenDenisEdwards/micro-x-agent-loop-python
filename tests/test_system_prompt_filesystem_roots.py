"""Tests for the filesystem-root surfacing in the system prompt — ensures the
model is told about FILESYSTEM_ALLOWED_DIRS / FILESYSTEM_READONLY_DIRS so it
won't refuse a request just because a path is outside its working directory.
"""

from __future__ import annotations

import os
import unittest

from micro_x_agent_loop.system_prompt import (
    filesystem_roots_from_mcp_config,
    get_system_prompt,
)


class FilesystemRootsFromMcpConfigTests(unittest.TestCase):
    def test_empty_config_returns_empty_lists(self) -> None:
        extra, ro = filesystem_roots_from_mcp_config({})
        self.assertEqual([], extra)
        self.assertEqual([], ro)

    def test_no_filesystem_block(self) -> None:
        extra, ro = filesystem_roots_from_mcp_config({"other": {"env": {}}})
        self.assertEqual([], extra)
        self.assertEqual([], ro)

    def test_no_env(self) -> None:
        extra, ro = filesystem_roots_from_mcp_config({"filesystem": {}})
        self.assertEqual([], extra)
        self.assertEqual([], ro)

    def test_parses_split_by_pathsep(self) -> None:
        joined_extra = os.pathsep.join(["C:\\path one", "C:\\path two"])
        joined_ro = "C:\\path three"
        config = {
            "filesystem": {
                "env": {
                    "FILESYSTEM_ALLOWED_DIRS": joined_extra,
                    "FILESYSTEM_READONLY_DIRS": joined_ro,
                }
            }
        }
        extra, ro = filesystem_roots_from_mcp_config(config)
        self.assertEqual(["C:\\path one", "C:\\path two"], extra)
        self.assertEqual(["C:\\path three"], ro)

    def test_skips_blank_entries(self) -> None:
        joined = os.pathsep.join(["C:\\real", "", "  "])
        config = {"filesystem": {"env": {"FILESYSTEM_ALLOWED_DIRS": joined}}}
        extra, _ = filesystem_roots_from_mcp_config(config)
        self.assertEqual(["C:\\real"], extra)


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
