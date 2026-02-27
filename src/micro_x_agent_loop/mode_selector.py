"""Stage 1 structural pattern matching for mode selection.

Analyzes user prompts for signals that indicate whether compiled task mode
or prompt mode is more appropriate. Pure computation — no dependencies on
agent, provider, or turn engine.
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


# ---------------------------------------------------------------------------
# Signal detectors
# ---------------------------------------------------------------------------

# Batch processing: "each", "all", "every" in iteration context,
# or numeric quantities with collection nouns ("100 emails", "last 50 jobs")
_ACTION_VERBS = r"(?:search|score|find|check|read|scan|process|evaluate|analyze|analyse|get|fetch|list|review|rate|rank|compare|extract|collect|gather|filter|exclude|summarize|summarise)"
_COLLECTION_NOUNS = r"(?:jobs?|emails?|messages?|listings?|items?|results?|entries?|records?|candidates?|roles?|positions?|files?|documents?|pages?|posts?|articles?)"

_BATCH_PATTERNS = [
    re.compile(rf"{_ACTION_VERBS}\s+(?:each|all|every)\b", re.IGNORECASE),
    re.compile(rf"\b(?:each|all|every)\s+{_COLLECTION_NOUNS}", re.IGNORECASE),
    re.compile(rf"\bfor\s+(?:each|all|every)\b", re.IGNORECASE),
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
        lines.append(
            f"  {signal.name} ({signal.strength.value}): "
            f'"{signal.matched_text}"'
        )
    lines.append(
        f"  Signals: {analysis.strong_count} strong, "
        f"{analysis.moderate_count} moderate, "
        f"{analysis.supportive_count} supportive"
    )
    return "\n".join(lines)
