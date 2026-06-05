"""Direct tests for SessionController — pure formatter, no side effects."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.services.session_controller import SessionController


def _session(sid: str = "abcd1234efgh", *, title: str = "My Session", parent: str | None = None) -> dict:
    return {
        "id": sid,
        "title": title,
        "parent_session_id": parent,
        "created_at": "2026-02-19T00:00:00+00:00",
        "updated_at": "2026-02-19T01:00:00+00:00",
        "status": "active",
    }


class ShortIdTests(unittest.TestCase):
    def test_truncates_long_id(self) -> None:
        c = SessionController(line_prefix=" ")
        self.assertEqual("abcd1234", c.short_id("abcd1234efghij"))

    def test_returns_short_id_unchanged(self) -> None:
        c = SessionController(line_prefix=" ")
        self.assertEqual("abc", c.short_id("abc"))

    def test_custom_length(self) -> None:
        c = SessionController(line_prefix=" ", short_id_len=4)
        self.assertEqual("abcd", c.short_id("abcd1234efghij"))


class FormatSessionListEntryTests(unittest.TestCase):
    def test_active_session_marked_with_star(self) -> None:
        c = SessionController(line_prefix="  ")
        out = c.format_session_list_entry(_session("sid-active"), active_session_id="sid-active")
        self.assertIn("* My Session", out)
        self.assertNotIn("  My Session", out.replace("* My Session", ""))

    def test_inactive_session_has_space_marker(self) -> None:
        c = SessionController(line_prefix=" ")
        out = c.format_session_list_entry(_session("sid-1"), active_session_id="other")
        # Inactive entries start with the line_prefix then a space then the title
        self.assertIn(" My Session", out)
        self.assertNotIn("* My Session", out)

    def test_includes_id_status_dates_parent(self) -> None:
        c = SessionController(line_prefix=" ")
        s = _session("sid-1", parent="parent-id")
        out = c.format_session_list_entry(s, active_session_id="other")
        for token in ("id=sid-1", "status=active", "created=2026-02-19T00:00:00+00:00",
                      "updated=2026-02-19T01:00:00+00:00", "parent=parent-id"):
            self.assertIn(token, out)

    def test_dash_for_missing_parent(self) -> None:
        c = SessionController(line_prefix=" ")
        out = c.format_session_list_entry(_session("sid-1", parent=None), active_session_id=None)
        self.assertIn("parent=-", out)

    def test_falls_back_to_id_when_title_missing(self) -> None:
        c = SessionController(line_prefix=" ")
        s = _session("sid-1")
        del s["title"]
        out = c.format_session_list_entry(s, active_session_id=None)
        # short_id of "sid-1" is "sid-1" (<=8), title falls back to id
        self.assertIn("sid-1 [sid-1]", out)


class FormatResumedSummaryLinesTests(unittest.TestCase):
    def _full_summary(self) -> dict:
        return {
            "created_at": "2026-02-19T00:00:00+00:00",
            "updated_at": "2026-02-19T01:00:00+00:00",
            "message_count": 12,
            "user_message_count": 5,
            "assistant_message_count": 7,
            "checkpoint_count": 2,
            "last_user_preview": "What is the weather",
            "last_assistant_preview": "Here is the forecast",
        }

    def test_renders_header_and_core_lines(self) -> None:
        c = SessionController(line_prefix=" ")
        lines = c.format_resumed_summary_lines(self._full_summary())
        joined = "\n".join(lines)
        self.assertIn("Session summary", joined)
        self.assertIn("Created: 2026-02-19T00:00:00+00:00", joined)
        self.assertIn("Updated: 2026-02-19T01:00:00+00:00", joined)
        self.assertIn("Messages: 12 (user=5, assistant=7)", joined)
        self.assertIn("Checkpoints: 2", joined)
        self.assertIn("Last user: What is the weather", joined)
        self.assertIn("Last assistant: Here is the forecast", joined)

    def test_omits_previews_when_empty(self) -> None:
        c = SessionController(line_prefix=" ")
        summary = self._full_summary()
        summary["last_user_preview"] = ""
        summary["last_assistant_preview"] = ""
        lines = c.format_resumed_summary_lines(summary)
        joined = "\n".join(lines)
        self.assertNotIn("Last user", joined)
        self.assertNotIn("Last assistant", joined)


if __name__ == "__main__":
    unittest.main()
