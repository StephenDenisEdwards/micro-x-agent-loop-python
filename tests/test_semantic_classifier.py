"""Tests for semantic_classifier module."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.semantic_classifier import (
    TaskClassification,
    build_stage3_prompt,
    classify_stage1,
    classify_stage2,
    classify_task,
    parse_stage3_response,
)
from micro_x_agent_loop.task_taxonomy import TaskType

COMPLEXITY_KEYWORDS = [
    "design",
    "architect",
    "analyze",
    "analyse",
    "explain why",
    "compare",
    "evaluate",
    "debug",
    "refactor",
    "plan",
    "implement",
]


class Stage1Tests(unittest.TestCase):
    """Tests for rule-based classification (Stage 1)."""

    def test_tool_continuation(self) -> None:
        result = classify_stage1(
            user_message="anything",
            has_tools=True,
            turn_iteration=1,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.TOOL_CONTINUATION)
        self.assertEqual(result.stage, "rules")

    def test_greeting_trivial(self) -> None:
        result = classify_stage1(
            user_message="hello",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.TRIVIAL)

    def test_thanks_trivial(self) -> None:
        result = classify_stage1(
            user_message="thanks",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.TRIVIAL)

    def test_complexity_guard(self) -> None:
        result = classify_stage1(
            user_message="please analyze this code",
            has_tools=True,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=COMPLEXITY_KEYWORDS,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.ANALYSIS)

    def test_summarize_pattern(self) -> None:
        result = classify_stage1(
            user_message="summarize this document",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.SUMMARIZATION)

    def test_code_generation_pattern(self) -> None:
        result = classify_stage1(
            user_message="write a function that calculates fibonacci numbers",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.CODE_GENERATION)

    def test_code_review_pattern(self) -> None:
        result = classify_stage1(
            user_message="review this code and find the bug in the implementation",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.CODE_REVIEW)

    def test_factual_question(self) -> None:
        result = classify_stage1(
            user_message="what is the difference between TCP and UDP?",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_type, TaskType.FACTUAL_LOOKUP)

    def test_no_match_returns_none(self) -> None:
        result = classify_stage1(
            user_message=(
                "I need to process these files and transform the data into a report"
                " format that includes aggregated metrics across all departments"
            ),
            has_tools=True,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsNone(result)

    def test_short_followup(self) -> None:
        result = classify_stage1(
            user_message="ok go ahead",
            has_tools=False,
            turn_iteration=0,
            turn_number=3,
            complexity_keywords=[],
        )
        self.assertIsNotNone(result)
        # Should be trivial (greeting pattern)
        self.assertIn(result.task_type, {TaskType.TRIVIAL, TaskType.CONVERSATIONAL})


class Stage2Tests(unittest.TestCase):
    """Tests for keyword-vector classification (Stage 2)."""

    def test_code_message(self) -> None:
        result = classify_stage2("implement a new function to sort the list")
        self.assertEqual(result.stage, "keywords")
        self.assertIn(result.task_type, {TaskType.CODE_GENERATION, TaskType.ANALYSIS})

    def test_summarization_message(self) -> None:
        result = classify_stage2("give me a brief overview and summary of the key highlights")
        self.assertEqual(result.task_type, TaskType.SUMMARIZATION)

    def test_empty_message(self) -> None:
        result = classify_stage2("")
        self.assertEqual(result.task_type, TaskType.CONVERSATIONAL)
        self.assertLessEqual(result.confidence, 0.5)

    def test_analysis_message(self) -> None:
        result = classify_stage2("evaluate the architecture and compare the design approaches")
        self.assertEqual(result.task_type, TaskType.ANALYSIS)

    def test_confidence_range(self) -> None:
        result = classify_stage2("tell me about python")
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_embedding_path_used_when_available(self) -> None:
        """When query_embedding and index are provided, uses embedding classification."""

        class FakeIndex:
            is_ready = True

            def classify(self, embedding: list[float]) -> tuple[str, float]:
                return ("code_generation", 0.82)

        result = classify_stage2(
            "get the last 5 emails",
            query_embedding=[0.1, 0.2, 0.3],
            task_embedding_index=FakeIndex(),
        )
        self.assertEqual(result.stage, "embeddings")
        self.assertEqual(result.task_type, TaskType.CODE_GENERATION)
        self.assertAlmostEqual(result.confidence, 0.91, places=1)

    def test_embedding_fallback_when_index_not_ready(self) -> None:
        """Falls back to keywords when index is not ready."""

        class FakeIndex:
            is_ready = False

            def classify(self, embedding: list[float]) -> tuple[str, float]:
                raise AssertionError("should not be called")

        result = classify_stage2(
            "summarize this document",
            query_embedding=[0.1, 0.2, 0.3],
            task_embedding_index=FakeIndex(),
        )
        self.assertEqual(result.stage, "keywords")

    def test_embedding_fallback_when_no_embedding(self) -> None:
        """Falls back to keywords when query_embedding is None."""
        result = classify_stage2(
            "summarize this document",
            query_embedding=None,
            task_embedding_index=None,
        )
        self.assertEqual(result.stage, "keywords")

    def test_embedding_low_similarity_falls_back(self) -> None:
        """Falls back to keywords when embedding similarity is below threshold."""

        class FakeIndex:
            is_ready = True

            def classify(self, embedding: list[float]) -> tuple[str, float]:
                return ("trivial", 0.15)  # Below 0.3 threshold

        result = classify_stage2(
            "evaluate the architecture and compare the design approaches",
            query_embedding=[0.1, 0.2, 0.3],
            task_embedding_index=FakeIndex(),
        )
        self.assertEqual(result.stage, "keywords")
        self.assertEqual(result.task_type, TaskType.ANALYSIS)


class Stage3Tests(unittest.TestCase):
    """Tests for LLM classification parsing."""

    def test_valid_json(self) -> None:
        result = parse_stage3_response('{"task_type": "code_generation", "confidence": 0.9}')
        self.assertEqual(result.task_type, TaskType.CODE_GENERATION)
        self.assertAlmostEqual(result.confidence, 0.9)
        self.assertEqual(result.stage, "llm")

    def test_json_in_code_block(self) -> None:
        result = parse_stage3_response('```json\n{"task_type": "analysis", "confidence": 0.85}\n```')
        self.assertEqual(result.task_type, TaskType.ANALYSIS)

    def test_invalid_json(self) -> None:
        result = parse_stage3_response("not json at all")
        self.assertEqual(result.task_type, TaskType.CONVERSATIONAL)
        self.assertLessEqual(result.confidence, 0.5)

    def test_unknown_task_type(self) -> None:
        result = parse_stage3_response('{"task_type": "unknown_type", "confidence": 0.8}')
        self.assertEqual(result.task_type, TaskType.CONVERSATIONAL)
        self.assertEqual(result.confidence, 0.5)

    def test_build_prompt(self) -> None:
        prompt = build_stage3_prompt("write a test for the login feature")
        self.assertIn("write a test", prompt)
        self.assertIn("task_type", prompt)


class PipelineTests(unittest.TestCase):
    """Tests for the combined classify_task pipeline."""

    def test_rules_only_strategy(self) -> None:
        result = classify_task(
            user_message="hello",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
            strategy="rules",
        )
        self.assertEqual(result.task_type, TaskType.TRIVIAL)
        self.assertEqual(result.stage, "rules")

    def test_rules_keywords_strategy(self) -> None:
        # Message that won't match rules confidently
        result = classify_task(
            user_message="process the data and generate a summary report with key highlights",
            has_tools=True,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
            strategy="rules+keywords",
        )
        self.assertIsNotNone(result)
        self.assertIn(result.stage, {"rules", "keywords"})

    def test_tool_continuation_always_rules(self) -> None:
        result = classify_task(
            user_message="anything",
            has_tools=True,
            turn_iteration=2,
            turn_number=5,
            complexity_keywords=COMPLEXITY_KEYWORDS,
            strategy="rules+keywords",
        )
        self.assertEqual(result.task_type, TaskType.TOOL_CONTINUATION)
        self.assertEqual(result.stage, "rules")

    def test_complexity_guard_overrides(self) -> None:
        result = classify_task(
            user_message="hello, can you design a new system?",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=COMPLEXITY_KEYWORDS,
            strategy="rules+keywords",
        )
        self.assertEqual(result.task_type, TaskType.ANALYSIS)

    def test_returns_task_classification(self) -> None:
        result = classify_task(
            user_message="test message",
            has_tools=False,
            turn_iteration=0,
            turn_number=1,
            complexity_keywords=[],
        )
        self.assertIsInstance(result, TaskClassification)
        self.assertIsInstance(result.task_type, TaskType)
        self.assertIn(result.stage, {"rules", "keywords", "embeddings", "llm"})
        self.assertGreater(result.confidence, 0.0)
