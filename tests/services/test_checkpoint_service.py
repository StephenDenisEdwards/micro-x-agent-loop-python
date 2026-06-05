"""Direct tests for CheckpointService — pure formatter, no side effects."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.services.checkpoint_service import CheckpointService


class FormatCheckpointListEntryTests(unittest.TestCase):
    def test_renders_short_id_id_created_and_tools(self) -> None:
        c = CheckpointService(line_prefix=" ")
        entry = c.format_checkpoint_list_entry(
            {
                "id": "cp1234567890",
                "created_at": "2026-02-19T00:00:00+00:00",
                "tools": ["write_file", "edit_file"],
                "user_preview": "",
            }
        )
        self.assertIn("[cp123456]", entry)
        self.assertIn("id=cp1234567890", entry)
        self.assertIn("created=2026-02-19T00:00:00+00:00", entry)
        self.assertIn("tools=write_file, edit_file", entry)
        # No preview block when empty
        self.assertNotIn("prompt=", entry)

    def test_dash_for_missing_tools(self) -> None:
        c = CheckpointService(line_prefix=" ")
        entry = c.format_checkpoint_list_entry(
            {"id": "cp1", "created_at": "t", "tools": [], "user_preview": ""},
        )
        self.assertIn("tools=n/a", entry)

    def test_includes_user_preview_when_present(self) -> None:
        c = CheckpointService(line_prefix=" ")
        entry = c.format_checkpoint_list_entry(
            {
                "id": "cp1",
                "created_at": "t",
                "tools": ["x"],
                "user_preview": "Rename foo to bar",
            }
        )
        self.assertIn('prompt="Rename foo to bar"', entry)


class FormatRewindOutcomeLinesTests(unittest.TestCase):
    def test_header_and_per_path_outcomes(self) -> None:
        c = CheckpointService(line_prefix=" ")
        outcomes = [
            {"path": "a.txt", "status": "restored", "detail": ""},
            {"path": "b.py", "status": "skipped", "detail": "no checkpoint blob"},
        ]
        lines = c.format_rewind_outcome_lines("cp-xyz", outcomes)
        joined = "\n".join(lines)
        self.assertIn("Rewind cp-xyz results", joined)
        self.assertIn("a.txt: restored", joined)
        # detail string is rendered in parens
        self.assertIn("b.py: skipped (no checkpoint blob)", joined)

    def test_empty_outcomes_yields_header_only(self) -> None:
        c = CheckpointService(line_prefix=" ")
        lines = c.format_rewind_outcome_lines("cp", [])
        self.assertEqual(1, len(lines))
        self.assertIn("Rewind cp results", lines[0])

    def test_line_prefix_applied_to_every_line(self) -> None:
        c = CheckpointService(line_prefix=">>> ")
        lines = c.format_rewind_outcome_lines("cp", [{"path": "f", "status": "ok", "detail": ""}])
        for line in lines:
            self.assertTrue(line.startswith(">>> "), msg=f"missing prefix in {line!r}")


if __name__ == "__main__":
    unittest.main()
