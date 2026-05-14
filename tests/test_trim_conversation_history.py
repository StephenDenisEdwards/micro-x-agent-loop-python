"""Tests for the role-aware trim and orphan-tool-result repair helpers."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.agent import (
    _find_safe_trim_count,
    _is_safe_message_head,
    _repair_orphan_head,
)


def _user_text(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant_tool_use(tool_use_id: str, name: str = "some_tool") -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_use_id, "name": name, "input": {}}],
    }


def _user_tool_result(tool_use_id: str, text: str = "ok") -> dict:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": text}],
    }


def _user_mixed(tool_use_id: str, text: str = "follow up") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"},
            {"type": "text", "text": text},
        ],
    }


class IsSafeMessageHeadTests(unittest.TestCase):
    def test_user_string_content_is_safe(self) -> None:
        self.assertTrue(_is_safe_message_head(_user_text("hello")))

    def test_assistant_message_is_unsafe(self) -> None:
        self.assertFalse(_is_safe_message_head(_assistant_tool_use("toolu_1")))

    def test_pure_tool_result_user_message_is_unsafe(self) -> None:
        self.assertFalse(_is_safe_message_head(_user_tool_result("toolu_1")))

    def test_mixed_user_message_with_text_is_safe(self) -> None:
        self.assertTrue(_is_safe_message_head(_user_mixed("toolu_1")))

    def test_unknown_role_is_unsafe(self) -> None:
        self.assertFalse(_is_safe_message_head({"role": "system", "content": "x"}))


class FindSafeTrimCountTests(unittest.TestCase):
    def test_no_trim_when_below_max(self) -> None:
        messages = [_user_text("hi"), _assistant_tool_use("toolu_1"), _user_tool_result("toolu_1")]
        self.assertEqual(0, _find_safe_trim_count(messages, max_messages=10))

    def test_disabled_when_max_zero_or_negative(self) -> None:
        messages = [_user_text("hi")] * 5
        self.assertEqual(0, _find_safe_trim_count(messages, max_messages=0))
        self.assertEqual(0, _find_safe_trim_count(messages, max_messages=-1))

    def test_naive_trim_would_orphan_tool_result_is_skipped_forward(self) -> None:
        # Layout that reproduces the bug: compacted head + verbatim pairs.
        messages = [
            _user_text("merged_first"),              # [0]
            _assistant_tool_use("toolu_1"),          # [1]
            _user_tool_result("toolu_1"),            # [2]
            _assistant_tool_use("toolu_2"),          # [3]
            _user_tool_result("toolu_2"),            # [4]
            _user_text("next user prompt"),          # [5]
            _assistant_tool_use("toolu_3"),          # [6]
            _user_tool_result("toolu_3"),            # [7]
        ]
        # max=6 → naive remove_count=2 would put a tool_result at the head.
        # Helper should walk forward to index 5 (the safe user text message).
        self.assertEqual(5, _find_safe_trim_count(messages, max_messages=6))

    def test_no_safe_boundary_returns_zero(self) -> None:
        # Everything past the naive boundary is assistant or tool_result —
        # nothing safe to land on. Helper must refuse to trim.
        messages = [
            _user_text("merged_first"),
            _assistant_tool_use("toolu_1"),
            _user_tool_result("toolu_1"),
            _assistant_tool_use("toolu_2"),
            _user_tool_result("toolu_2"),
        ]
        self.assertEqual(0, _find_safe_trim_count(messages, max_messages=2))

    def test_safe_boundary_at_naive_target_is_used(self) -> None:
        # If the naive target already lands on a safe user message, return it.
        messages = [
            _user_text("a"),
            _assistant_tool_use("toolu_1"),
            _user_tool_result("toolu_1"),
            _user_text("b"),
            _user_text("c"),
        ]
        # max=2 → naive remove_count=3, which lands on _user_text("b"). Safe.
        self.assertEqual(3, _find_safe_trim_count(messages, max_messages=2))


class RepairOrphanHeadTests(unittest.TestCase):
    def test_clean_head_unchanged(self) -> None:
        messages = [_user_text("hi"), _assistant_tool_use("toolu_1"), _user_tool_result("toolu_1")]
        repaired, dropped = _repair_orphan_head(messages)
        self.assertEqual(0, dropped)
        self.assertEqual(messages, repaired)

    def test_drops_leading_orphan_tool_result(self) -> None:
        messages = [
            _user_tool_result("toolu_orphan"),  # orphan — no preceding tool_use
            _user_text("new prompt"),
            _assistant_tool_use("toolu_1"),
            _user_tool_result("toolu_1"),
        ]
        repaired, dropped = _repair_orphan_head(messages)
        self.assertEqual(1, dropped)
        self.assertEqual(3, len(repaired))
        self.assertTrue(_is_safe_message_head(repaired[0]))

    def test_drops_leading_assistant_and_orphan_tool_result_pair(self) -> None:
        # An assistant tool_use at head is also invalid — must drop until a
        # user string-content message appears.
        messages = [
            _assistant_tool_use("toolu_orphan"),
            _user_tool_result("toolu_orphan"),
            _user_text("safe head"),
            _assistant_tool_use("toolu_1"),
            _user_tool_result("toolu_1"),
        ]
        repaired, dropped = _repair_orphan_head(messages)
        self.assertEqual(2, dropped)
        self.assertEqual("safe head", repaired[0]["content"])

    def test_empty_list_unchanged(self) -> None:
        repaired, dropped = _repair_orphan_head([])
        self.assertEqual(0, dropped)
        self.assertEqual([], repaired)


if __name__ == "__main__":
    unittest.main()
