"""Tests for per-turn model routing classifier."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.turn_classifier import TurnClassification, classify_turn

_DEFAULT_KEYWORDS = [
    "design", "architect", "analyze", "analyse", "explain why",
    "compare", "evaluate", "debug", "refactor", "plan", "implement",
]


class ClassifyTurnTests(unittest.TestCase):
    """Core classification logic."""

    def _classify(
        self,
        user_message: str = "hello",
        *,
        has_tools: bool = True,
        turn_iteration: int = 0,
        turn_number: int = 1,
        max_user_chars: int = 200,
        short_followup_chars: int = 50,
        complexity_keywords: list[str] | None = None,
    ) -> TurnClassification:
        return classify_turn(
            user_message=user_message,
            has_tools=has_tools,
            turn_iteration=turn_iteration,
            turn_number=turn_number,
            max_user_chars=max_user_chars,
            short_followup_chars=short_followup_chars,
            complexity_keywords=_DEFAULT_KEYWORDS if complexity_keywords is None else complexity_keywords,
        )

    # -- Rule 1: Tool-result continuation --

    def test_tool_result_continuation_routes_cheap(self) -> None:
        result = self._classify(turn_iteration=1)
        self.assertTrue(result.use_cheap_model)
        self.assertEqual(result.rule, "tool_result_continuation")

    def test_tool_result_continuation_iteration_2(self) -> None:
        result = self._classify(turn_iteration=2)
        self.assertTrue(result.use_cheap_model)
        self.assertEqual(result.rule, "tool_result_continuation")

    # -- Rule 2: Short conversational --

    def test_short_conversational_no_tools(self) -> None:
        result = self._classify("hi there", has_tools=False)
        self.assertTrue(result.use_cheap_model)
        self.assertEqual(result.rule, "short_conversational")

    def test_short_conversational_with_tools_not_matched(self) -> None:
        result = self._classify("hi there", has_tools=True)
        # Has tools, so rule 2 doesn't match — should fall to default
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "default")

    def test_long_message_no_tools_not_matched(self) -> None:
        result = self._classify("x" * 300, has_tools=False, max_user_chars=200)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "default")

    # -- Rule 3: Short follow-up --

    def test_short_followup_turn_2(self) -> None:
        result = self._classify("yes", turn_number=2)
        self.assertTrue(result.use_cheap_model)
        self.assertEqual(result.rule, "short_followup")

    def test_short_followup_turn_1_not_matched(self) -> None:
        """Turn 1 should NOT match the follow-up rule."""
        result = self._classify("yes", turn_number=1, has_tools=True)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "default")

    def test_followup_too_long(self) -> None:
        result = self._classify("please continue with the next step", turn_number=2, short_followup_chars=10)
        # Message exceeds short_followup_chars — shouldn't match rule 3
        self.assertFalse(result.use_cheap_model)

    # -- Rule 5: Complexity guard --

    def test_complexity_keyword_overrides_tool_continuation(self) -> None:
        result = self._classify("please analyze this data", turn_iteration=1)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "complexity_guard")

    def test_complexity_keyword_overrides_short_conversational(self) -> None:
        result = self._classify("debug this", has_tools=False)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "complexity_guard")

    def test_complexity_keyword_overrides_short_followup(self) -> None:
        result = self._classify("refactor", turn_number=3)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "complexity_guard")

    def test_complexity_keyword_case_insensitive(self) -> None:
        result = self._classify("DESIGN a system", turn_iteration=1)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "complexity_guard")

    def test_complexity_multi_word_keyword(self) -> None:
        result = self._classify("explain why this works", turn_iteration=1)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "complexity_guard")

    # -- Rule 6: Default --

    def test_default_main_model(self) -> None:
        result = self._classify("tell me about the weather in London", has_tools=True)
        self.assertFalse(result.use_cheap_model)
        self.assertEqual(result.rule, "default")

    # -- Edge cases --

    def test_empty_message(self) -> None:
        result = self._classify("", has_tools=False)
        self.assertTrue(result.use_cheap_model)
        self.assertEqual(result.rule, "short_conversational")

    def test_no_complexity_keywords(self) -> None:
        """With empty keyword list, complexity guard never triggers."""
        result = self._classify("design a system", turn_iteration=1, complexity_keywords=[])
        self.assertTrue(result.use_cheap_model)
        self.assertEqual(result.rule, "tool_result_continuation")

    def test_classification_is_frozen(self) -> None:
        result = self._classify("hello")
        with self.assertRaises(AttributeError):
            result.use_cheap_model = True  # type: ignore[misc]


class ClassifyTurnReturnTypeTests(unittest.TestCase):
    """Verify the TurnClassification dataclass structure."""

    def test_fields_present(self) -> None:
        result = classify_turn(
            user_message="hello",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            max_user_chars=200,
            short_followup_chars=50,
            complexity_keywords=[],
        )
        self.assertIsInstance(result.use_cheap_model, bool)
        self.assertIsInstance(result.reason, str)
        self.assertIsInstance(result.rule, str)
        self.assertTrue(len(result.reason) > 0)
        self.assertTrue(len(result.rule) > 0)


if __name__ == "__main__":
    unittest.main()
