"""Mode selection: structural pattern matching (Stage 1) and LLM classification (Stage 2).

Stage 1 analyzes user prompts for signals that indicate whether compiled task
mode or prompt mode is more appropriate.  Stage 2 builds a classification
prompt for an LLM to resolve ambiguous cases.  Pure computation — no async,
no provider dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SignalStrength(Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    SUPPORTIVE = "supportive"


class RecommendedMode(Enum):
    PROMPT = "PROMPT"
    COMPILED = "COMPILED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class DetectedSignal:
    name: str
    strength: SignalStrength
    matched_text: str


@dataclass(frozen=True)
class ModeAnalysis:
    recommended_mode: RecommendedMode
    signals: tuple[DetectedSignal, ...]
    strong_count: int
    moderate_count: int
    supportive_count: int


@dataclass(frozen=True)
class Stage2Result:
    recommended_mode: RecommendedMode
    reasoning: str


# ---------------------------------------------------------------------------
# Signal detectors
# ---------------------------------------------------------------------------

# Batch processing: "each", "all", "every" in iteration context,
# or numeric quantities with collection nouns ("100 emails", "last 50 jobs")
_ACTION_VERBS = (
    r"(?:search|score|find|check|read|scan|process|evaluate|analyze|analyse"
    r"|get|fetch|list|review|rate|rank|compare|extract|collect|gather|filter"
    r"|exclude|summarize|summarise)"
)
_COLLECTION_NOUNS = (
    r"(?:jobs?|emails?|messages?|listings?|items?|results?|entries?|records?"
    r"|candidates?|roles?|positions?|files?|documents?|pages?|posts?|articles?)"
)

_BATCH_PATTERNS = [
    re.compile(rf"{_ACTION_VERBS}\s+(?:each|all|every)\b", re.IGNORECASE),
    re.compile(rf"\b(?:each|all|every)\s+{_COLLECTION_NOUNS}", re.IGNORECASE),
    re.compile(r"\bfor\s+(?:each|all|every)\b", re.IGNORECASE),
    # Numeric quantities (>=2): "100 emails", "last 50 jobs", "the 20 results"
    re.compile(rf"\b(?:last|top|first|the)?\s*(?:[2-9]|\d{{2,}})\s+{_COLLECTION_NOUNS}", re.IGNORECASE),
]

# Scoring / ranking
_SCORING_PATTERNS = [
    re.compile(r"\b(?:score|scoring)\b", re.IGNORECASE),
    re.compile(r"\b(?:rank|ranking|ranked)\b", re.IGNORECASE),
    re.compile(r"\b(?:rate|rating|rated)\b", re.IGNORECASE),
    re.compile(r"\bevaluate\b", re.IGNORECASE),
    re.compile(r"\bcompare\b", re.IGNORECASE),
]

# Statistics / aggregation
_STATS_PATTERNS = [
    re.compile(r"\b(?:count|total)\b", re.IGNORECASE),
    re.compile(r"\baverage\b", re.IGNORECASE),
    re.compile(r"\bdistribution\b", re.IGNORECASE),
    re.compile(r"\bsummary\s+statistics\b", re.IGNORECASE),
    re.compile(r"\bstatistics\b", re.IGNORECASE),
    re.compile(r"\b(?:summaries|summarize|summarise)\b", re.IGNORECASE),
]

# Mandatory fields
_MANDATORY_PATTERNS = [
    re.compile(r"\bmust\s+include\b", re.IGNORECASE),
    re.compile(r"\balways\s+include\b", re.IGNORECASE),
    re.compile(r"\brequired\b", re.IGNORECASE),
    re.compile(r"\bensure\b", re.IGNORECASE),
]

# Structured output
_STRUCTURED_OUTPUT_PATTERNS = [
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\btemplate\b", re.IGNORECASE),
    re.compile(r"\bmarkdown\b", re.IGNORECASE),
    re.compile(r"\bjson\b", re.IGNORECASE),
    re.compile(r"\bcsv\b", re.IGNORECASE),
]

# Multiple data sources — grouped so related keywords (e.g. Gmail/email)
# count as one source, not two.
_SOURCE_GROUPS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("email", [re.compile(r"\bgmail\b", re.IGNORECASE), re.compile(r"\bemail(?:s)?\b", re.IGNORECASE)]),
    ("linkedin", [re.compile(r"\blinkedin\b", re.IGNORECASE)]),
    ("calendar", [re.compile(r"\bcalendar\b", re.IGNORECASE)]),
    ("slack", [re.compile(r"\bslack\b", re.IGNORECASE)]),
    ("jira", [re.compile(r"\bjira\b", re.IGNORECASE)]),
    ("github", [re.compile(r"\bgithub\b", re.IGNORECASE)]),
    ("drive", [re.compile(r"\bdrive\b", re.IGNORECASE)]),
]

# Reproducibility
_REPRODUCIBILITY_PATTERNS = [
    re.compile(r"\bdaily\b", re.IGNORECASE),
    re.compile(r"\brecurring\b", re.IGNORECASE),
    re.compile(r"\bevery\s+morning\b", re.IGNORECASE),
    re.compile(r"\bevery\s+day\b", re.IGNORECASE),
    re.compile(r"\bsame\s+as\s+yesterday\b", re.IGNORECASE),
]


def _first_match(text: str, patterns: list[re.Pattern[str]]) -> str | None:
    """Return the first match text from any pattern, or None."""
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def _detect_batch(text: str) -> DetectedSignal | None:
    matched = _first_match(text, _BATCH_PATTERNS)
    if matched:
        return DetectedSignal("Batch processing", SignalStrength.STRONG, matched)
    return None


def _detect_scoring(text: str) -> DetectedSignal | None:
    matched = _first_match(text, _SCORING_PATTERNS)
    if matched:
        return DetectedSignal("Scoring/ranking", SignalStrength.STRONG, matched)
    return None


def _detect_stats(text: str) -> DetectedSignal | None:
    matched = _first_match(text, _STATS_PATTERNS)
    if matched:
        return DetectedSignal("Statistics/aggregation", SignalStrength.STRONG, matched)
    return None


def _detect_mandatory_fields(text: str) -> DetectedSignal | None:
    matched = _first_match(text, _MANDATORY_PATTERNS)
    if matched:
        return DetectedSignal("Mandatory fields", SignalStrength.MODERATE, matched)
    return None


def _detect_structured_output(text: str) -> DetectedSignal | None:
    matched = _first_match(text, _STRUCTURED_OUTPUT_PATTERNS)
    if matched:
        return DetectedSignal("Structured output", SignalStrength.MODERATE, matched)
    return None


def _detect_multiple_sources(text: str) -> DetectedSignal | None:
    found: list[str] = []
    for _group_name, patterns in _SOURCE_GROUPS:
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                found.append(m.group(0))
                break  # one match per group is enough
    if len(found) >= 2:
        return DetectedSignal(
            "Multiple data sources",
            SignalStrength.MODERATE,
            " + ".join(f'"{s}"' for s in found),
        )
    return None


def _detect_reproducibility(text: str) -> DetectedSignal | None:
    matched = _first_match(text, _REPRODUCIBILITY_PATTERNS)
    if matched:
        return DetectedSignal("Reproducibility", SignalStrength.SUPPORTIVE, matched)
    return None


_DETECTORS = [
    _detect_batch,
    _detect_scoring,
    _detect_stats,
    _detect_mandatory_fields,
    _detect_structured_output,
    _detect_multiple_sources,
    _detect_reproducibility,
]


def analyze_prompt(text: str) -> ModeAnalysis:
    """Analyze a user prompt and recommend an execution mode."""
    signals: list[DetectedSignal] = []
    for detector in _DETECTORS:
        signal = detector(text)
        if signal is not None:
            signals.append(signal)

    strong = sum(1 for s in signals if s.strength == SignalStrength.STRONG)
    moderate = sum(1 for s in signals if s.strength == SignalStrength.MODERATE)
    supportive = sum(1 for s in signals if s.strength == SignalStrength.SUPPORTIVE)

    if strong >= 2:
        mode = RecommendedMode.COMPILED
    elif len(signals) == 0:
        mode = RecommendedMode.PROMPT
    else:
        mode = RecommendedMode.AMBIGUOUS

    return ModeAnalysis(
        recommended_mode=mode,
        signals=tuple(signals),
        strong_count=strong,
        moderate_count=moderate,
        supportive_count=supportive,
    )


def format_analysis(analysis: ModeAnalysis) -> str:
    """Format a ModeAnalysis as diagnostic CLI output.

    Returns a multi-line string for COMPILED/AMBIGUOUS, a single line
    for PROMPT, or empty string if there is nothing to report.
    """
    if analysis.recommended_mode == RecommendedMode.PROMPT:
        return "[Mode Analysis] Recommendation: PROMPT (no compiled-mode signals detected)"

    lines: list[str] = []
    lines.append(f"[Mode Analysis] Recommendation: {analysis.recommended_mode.value}")
    for signal in analysis.signals:
        lines.append(f'  {signal.name} ({signal.strength.value}): "{signal.matched_text}"')
    lines.append(
        f"  Signals: {analysis.strong_count} strong, "
        f"{analysis.moderate_count} moderate, "
        f"{analysis.supportive_count} supportive"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 2 — LLM classification for ambiguous cases
# ---------------------------------------------------------------------------


def build_stage2_prompt(user_message: str, stage1: ModeAnalysis) -> str:
    """Build a classification prompt for the LLM to resolve an ambiguous case.

    The prompt provides the user's original message, Stage 1 signals, and
    guidance on how to decide between PROMPT and COMPILED modes.
    """
    signal_lines = (
        "\n".join(f'  - {s.name} ({s.strength.value}): "{s.matched_text}"' for s in stage1.signals) or "  (none)"
    )

    return f"""\
You are a task classifier. Given a user's prompt and pre-detected signals,
decide whether it should run in PROMPT mode or COMPILED mode.

PROMPT mode: conversational, single-turn responses — good for questions,
explanations, single-item tasks, and open-ended chat.

COMPILED mode: structured batch execution — good for tasks involving multiple
items, per-item processing, data collection across sources, scoring/ranking
many items, or deterministic repeatable workflows.

Consider:
- Item count: does the task involve processing multiple items (emails, jobs,
  documents) or just one?
- Data volume: will the task produce or consume large amounts of structured data?
- Deterministic requirements: does the task need to be repeatable or follow
  strict rules for each item?
- Batch structure: is there a clear per-item loop (fetch → process → output)?

When uncertain, lean toward COMPILED — the cost of running a batch task in
prompt mode is much higher than the cost of this classification call.

User's prompt:
{user_message}

Stage 1 signals detected:
{signal_lines}

Respond with exactly two lines:
Line 1: either PROMPT or COMPILED (nothing else)
Line 2: a brief reason (one sentence)"""


def parse_stage2_response(response_text: str) -> Stage2Result:
    """Parse the LLM's classification response into a Stage2Result.

    Looks for COMPILED or PROMPT (case-insensitive) in the response.
    Defaults to COMPILED if neither is found (asymmetric failure cost).
    """
    lines = response_text.strip().splitlines()
    first_line = lines[0].strip().upper() if lines else ""

    if "COMPILED" in first_line:
        mode = RecommendedMode.COMPILED
    elif "PROMPT" in first_line:
        mode = RecommendedMode.PROMPT
    else:
        # Scan the whole response as a fallback
        upper = response_text.upper()
        if "COMPILED" in upper:
            mode = RecommendedMode.COMPILED
        elif "PROMPT" in upper:
            mode = RecommendedMode.PROMPT
        else:
            mode = RecommendedMode.COMPILED  # default: lean toward compiled

    reasoning = lines[1].strip() if len(lines) >= 2 else ""
    return Stage2Result(recommended_mode=mode, reasoning=reasoning)


def format_stage2_result(result: Stage2Result) -> str:
    """Format a Stage2Result as diagnostic CLI output."""
    line = f"[Mode Analysis] Stage 2 override: {result.recommended_mode.value}"
    if result.reasoning:
        line += f'\n  Reasoning: "{result.reasoning}"'
    return line
