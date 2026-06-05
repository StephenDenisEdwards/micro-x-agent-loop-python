"""Tests for the role-aware trim and orphan-tool-result repair helpers."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.agent import (
    _find_safe_trim_count,
    _find_tail_orphan_tool_use_ids,
    _is_safe_message_head,
    _repair_orphan_head,
    _repair_orphan_tool_uses,
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


class RepairOrphanToolUsesTests(unittest.TestCase):
    def test_clean_history_unchanged(self) -> None:
        messages = [
            _user_text("hi"),
            _assistant_tool_use("toolu_1"),
            _user_tool_result("toolu_1"),
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        ]
        repaired, inserted = _repair_orphan_tool_uses(messages)
        self.assertEqual(0, inserted)
        self.assertEqual(messages, repaired)

    def test_orphan_at_tail_gets_synthetic_user_message(self) -> None:
        # Previous run was interrupted right after the assistant emitted a
        # tool_use; nothing follows. Repair must insert a synthetic user
        # tool_result so a new prompt won't violate Anthropic's pairing rule.
        messages = [
            _user_text("hi"),
            _assistant_tool_use("toolu_1"),
        ]
        repaired, inserted = _repair_orphan_tool_uses(messages)
        self.assertEqual(1, inserted)
        self.assertEqual(3, len(repaired))
        self.assertEqual("user", repaired[2]["role"])
        self.assertEqual([
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": __import__(
                    "micro_x_agent_loop.agent", fromlist=["_INTERRUPTED_TOOL_RESULT"],
                )._INTERRUPTED_TOOL_RESULT,
                "is_error": True,
            }
        ], repaired[2]["content"])

    def test_orphan_followed_by_new_user_prompt_inserts_in_between(self) -> None:
        # Reproduces the reported failure mode: previous turn died after
        # tool_use was persisted; the user typed a new prompt; the new prompt
        # message is now where the tool_result should be.
        messages = [
            _user_text("first prompt"),
            _assistant_tool_use("toolu_1"),
            _user_text("what is going on?"),
        ]
        repaired, inserted = _repair_orphan_tool_uses(messages)
        self.assertEqual(1, inserted)
        self.assertEqual(4, len(repaired))
        self.assertEqual("user", repaired[2]["role"])
        self.assertEqual(1, len(repaired[2]["content"]))
        self.assertEqual("toolu_1", repaired[2]["content"][0]["tool_use_id"])
        self.assertEqual("what is going on?", repaired[3]["content"])

    def test_partial_orphan_appends_to_existing_user_results(self) -> None:
        # Assistant emitted two tool_use blocks; only one tool_result was
        # appended (e.g. one tool ran and the second was cancelled). Repair
        # must add a synthetic tool_result for the missing id without
        # disturbing the existing one.
        messages = [
            _user_text("hi"),
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "t1", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "t2", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
                ],
            },
        ]
        repaired, inserted = _repair_orphan_tool_uses(messages)
        self.assertEqual(1, inserted)
        self.assertEqual(3, len(repaired))
        results = repaired[2]["content"]
        self.assertEqual(2, len(results))
        self.assertEqual("toolu_1", results[0]["tool_use_id"])
        self.assertEqual("toolu_2", results[1]["tool_use_id"])
        self.assertTrue(results[1].get("is_error"))

    def test_multiple_orphans_through_history_all_repaired(self) -> None:
        messages = [
            _user_text("p1"),
            _assistant_tool_use("toolu_a"),
            # missing tool_result for toolu_a
            _user_text("p2"),
            _assistant_tool_use("toolu_b"),
            # missing tool_result for toolu_b (also no following message)
        ]
        repaired, inserted = _repair_orphan_tool_uses(messages)
        self.assertEqual(2, inserted)
        # Original 4 + 2 synthetic = 6
        self.assertEqual(6, len(repaired))
        # Synthetic tool_results land at index 2 (between asst-a and p2) and
        # index 5 (after asst-b, since nothing followed).
        self.assertEqual("toolu_a", repaired[2]["content"][0]["tool_use_id"])
        self.assertEqual("p2", repaired[3]["content"])
        self.assertEqual("toolu_b", repaired[5]["content"][0]["tool_use_id"])

    def test_empty_messages_unchanged(self) -> None:
        repaired, inserted = _repair_orphan_tool_uses([])
        self.assertEqual(0, inserted)
        self.assertEqual([], repaired)


class FindTailOrphanToolUseIdsTests(unittest.TestCase):
    def test_empty_returns_empty(self) -> None:
        self.assertEqual([], _find_tail_orphan_tool_use_ids([]))

    def test_last_is_user_returns_empty(self) -> None:
        messages = [_user_text("hi")]
        self.assertEqual([], _find_tail_orphan_tool_use_ids(messages))

    def test_last_is_assistant_text_returns_empty(self) -> None:
        messages = [
            _user_text("hi"),
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        ]
        self.assertEqual([], _find_tail_orphan_tool_use_ids(messages))

    def test_last_is_assistant_tool_use_returns_ids(self) -> None:
        # The cancellation case: assistant emitted tool_use blocks and the run
        # was cancelled before the matching tool_result was appended.
        messages = [
            _user_text("hi"),
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "t1", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "t2", "input": {}},
                ],
            },
        ]
        self.assertEqual(["toolu_1", "toolu_2"], _find_tail_orphan_tool_use_ids(messages))

    def test_last_is_assistant_mixed_returns_only_tool_use_ids(self) -> None:
        messages = [
            _user_text("hi"),
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "thinking"},
                    {"type": "tool_use", "id": "toolu_x", "name": "t", "input": {}},
                ],
            },
        ]
        self.assertEqual(["toolu_x"], _find_tail_orphan_tool_use_ids(messages))


if __name__ == "__main__":
    unittest.main()
