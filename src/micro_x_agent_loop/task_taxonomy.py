"""Task taxonomy for semantic model routing.

Defines the fixed set of task types that map to routing policies.
Each task type represents a distinct class of LLM work with different
quality/cost trade-off requirements.
"""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    """Task types for semantic routing classification."""

    TRIVIAL = "trivial"                    # Greetings, acknowledgements, yes/no
    CONVERSATIONAL = "conversational"      # Short Q&A, clarifications
    FACTUAL_LOOKUP = "factual_lookup"      # Simple factual questions
    SUMMARIZATION = "summarization"        # Summarise text/results
    CODE_GENERATION = "code_generation"    # Write/edit code
    CODE_REVIEW = "code_review"            # Review/explain code
    ANALYSIS = "analysis"                  # Complex reasoning, planning, design
    TOOL_CONTINUATION = "tool_continuation"  # Processing tool results
    CREATIVE = "creative"                  # Writing, brainstorming


# Cost tier mapping: which task types can use cheap models
CHEAP_TASK_TYPES: frozenset[TaskType] = frozenset({
    TaskType.TRIVIAL,
    TaskType.CONVERSATIONAL,
    TaskType.FACTUAL_LOOKUP,
    TaskType.SUMMARIZATION,
    TaskType.TOOL_CONTINUATION,
})

MAIN_TASK_TYPES: frozenset[TaskType] = frozenset({
    TaskType.CODE_GENERATION,
    TaskType.CODE_REVIEW,
    TaskType.ANALYSIS,
    TaskType.CREATIVE,
})
