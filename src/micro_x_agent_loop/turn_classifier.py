"""Per-turn model routing classifier.

Pure-function classifier that decides whether a given LLM call within
a turn can be handled by a cheaper model.  No async, no state, no
provider dependency — trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnClassification:
    """Result of classifying a single LLM call for model routing."""

    use_cheap_model: bool
    reason: str   # Human-readable explanation (for logging)
    rule: str     # Machine-readable rule ID (for metrics)


def classify_turn(
    *,
    user_message: str,
    has_tools: bool,
    turn_iteration: int,
    turn_number: int,
    max_user_chars: int,
    short_followup_chars: int,
    complexity_keywords: list[str],
) -> TurnClassification:
    """Classify whether this LLM call can use a cheaper model.

    Args:
        user_message: The original user message for this turn.
        has_tools: Whether tool schemas are attached to this API call.
        turn_iteration: 0 = first LLM call in the turn (processing user
            message), 1+ = subsequent calls after tool execution.
        turn_number: The turn number within the session (1-based).
        max_user_chars: Threshold for "short conversational" messages.
        short_followup_chars: Threshold for "short follow-up" messages.
        complexity_keywords: Keywords that indicate the turn needs the
            main model (overrides cheap routing).

    Returns:
        A ``TurnClassification`` indicating whether to use the cheap model.
    """
    msg_lower = user_message.lower().strip()

    # Rule 5 (complexity guard) — checked FIRST so it overrides all cheap rules
    if _has_complexity_signal(msg_lower, complexity_keywords):
        return TurnClassification(
            use_cheap_model=False,
            reason="complexity keyword detected",
            rule="complexity_guard",
        )

    # Rule 1: Tool-result continuation (iteration > 0 in the while loop)
    if turn_iteration > 0:
        return TurnClassification(
            use_cheap_model=True,
            reason=f"tool-result continuation (iteration {turn_iteration})",
            rule="tool_result_continuation",
        )

    # Rule 2: Short conversational message (no tools, short, no complexity)
    if not has_tools and len(user_message) <= max_user_chars:
        return TurnClassification(
            use_cheap_model=True,
            reason=f"short conversational message ({len(user_message)} chars, no tools)",
            rule="short_conversational",
        )

    # Rule 3: Short follow-up in an established session
    if turn_number > 1 and len(user_message) <= short_followup_chars:
        return TurnClassification(
            use_cheap_model=True,
            reason=f"short follow-up ({len(user_message)} chars, turn {turn_number})",
            rule="short_followup",
        )

    # Rule 6: Default — use main model
    return TurnClassification(
        use_cheap_model=False,
        reason="default (no cheap routing rule matched)",
        rule="default",
    )


def _has_complexity_signal(msg_lower: str, keywords: list[str]) -> bool:
    """Check whether the user message contains any complexity keyword."""
    return any(kw in msg_lower for kw in keywords)
