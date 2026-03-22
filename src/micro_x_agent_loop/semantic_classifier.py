"""Semantic task classifier for cross-provider model routing.

Three-stage pipeline:
  Stage 1 (rules)      — Pattern matching, < 1ms, handles obvious cases.
  Stage 2 (embeddings) — Dense embeddings via Ollama, ~10ms, real semantic matching.
  Stage 2 (keywords)   — Keyword-vector fallback when embeddings unavailable, < 1ms.
  Stage 3 (LLM)        — Cheapest model classifies ambiguous tasks, ~200ms.

Pure functions (no async, no state) except for Stage 3 which requires a provider.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from micro_x_agent_loop.task_taxonomy import TaskType


@dataclass(frozen=True)
class TaskClassification:
    """Result of semantic task classification."""

    task_type: TaskType
    confidence: float        # 0.0–1.0
    stage: str               # "rules", "keywords", "llm"
    reason: str              # Human-readable explanation


# ---------------------------------------------------------------------------
# Stage 1: Rule-based classification
# ---------------------------------------------------------------------------

_GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure|got it|np|ty|thx|"
    r"good morning|good evening|good night|cheers|bye|goodbye|welcome|"
    r"sounds good|perfect|great|awesome|cool|nice|right|yep|nope|nah)\b",
    re.IGNORECASE,
)

_SUMMARIZE_PATTERNS = re.compile(
    r"\b(summarize|summarise|tldr|tl;dr|give me a summary|brief overview|"
    r"recap|condense|shorten)\b",
    re.IGNORECASE,
)

_CODE_GEN_PATTERNS = re.compile(
    r"\b(write|create|implement|build|generate|add|make|save)\b.*\b(function|class|"
    r"method|endpoint|api|script|module|component|test|code|file|program)\b",
    re.IGNORECASE,
)

_CODE_REVIEW_PATTERNS = re.compile(
    r"\b(review|explain|what does|how does|walk me through|trace|debug|"
    r"find the bug|what\'s wrong)\b.*\b(code|function|method|class|file|"
    r"implementation|error|bug|issue)\b",
    re.IGNORECASE,
)

_ANALYSIS_PATTERNS = re.compile(
    r"\b(design|architect|analyze|analyse|compare|evaluate|plan|"
    r"trade-?off|optimise|optimize|critique|suggest improvements|"
    r"pros and cons|deep dive|investigate|research|strategy)\b",
    re.IGNORECASE,
)

_CREATIVE_PATTERNS = re.compile(
    r"\b(write|draft|compose|brainstorm|ideate|come up with|"
    r"blog post|article|essay|story|email|message|letter|proposal|"
    r"presentation|pitch)\b",
    re.IGNORECASE,
)

_FACTUAL_PATTERNS = re.compile(
    r"\b(what is|what are|who is|when did|where is|how many|"
    r"define|meaning of|difference between|list of)\b",
    re.IGNORECASE,
)


def classify_stage1(
    *,
    user_message: str,
    has_tools: bool,
    turn_iteration: int,
    turn_number: int,
    complexity_keywords: list[str],
    max_trivial_chars: int = 30,
) -> TaskClassification | None:
    """Stage 1: Rule-based classification. Returns None if no confident match."""

    msg = user_message.strip()
    msg_lower = msg.lower()

    # Tool-result continuation (iteration > 0)
    if turn_iteration > 0:
        return TaskClassification(
            task_type=TaskType.TOOL_CONTINUATION,
            confidence=0.95,
            stage="rules",
            reason=f"tool-result continuation (iteration {turn_iteration})",
        )

    # Complexity guard — if complexity keywords present, don't classify as cheap
    if complexity_keywords and any(kw in msg_lower for kw in complexity_keywords):
        return TaskClassification(
            task_type=TaskType.ANALYSIS,
            confidence=0.85,
            stage="rules",
            reason="complexity keyword detected",
        )

    # Trivial: very short + greeting pattern
    if len(msg) <= max_trivial_chars and _GREETING_PATTERNS.match(msg):
        return TaskClassification(
            task_type=TaskType.TRIVIAL,
            confidence=0.95,
            stage="rules",
            reason="greeting/acknowledgement pattern",
        )

    # Summarization
    if _SUMMARIZE_PATTERNS.search(msg):
        return TaskClassification(
            task_type=TaskType.SUMMARIZATION,
            confidence=0.90,
            stage="rules",
            reason="summarization keyword detected",
        )

    # Code generation — check before creative to avoid false matches
    if _CODE_GEN_PATTERNS.search(msg):
        return TaskClassification(
            task_type=TaskType.CODE_GENERATION,
            confidence=0.85,
            stage="rules",
            reason="code generation pattern detected",
        )

    # Code review / explanation
    if _CODE_REVIEW_PATTERNS.search(msg):
        return TaskClassification(
            task_type=TaskType.CODE_REVIEW,
            confidence=0.85,
            stage="rules",
            reason="code review/explanation pattern detected",
        )

    # Analysis
    if _ANALYSIS_PATTERNS.search(msg):
        return TaskClassification(
            task_type=TaskType.ANALYSIS,
            confidence=0.85,
            stage="rules",
            reason="analysis/design pattern detected",
        )

    # Factual lookup
    if _FACTUAL_PATTERNS.search(msg):
        return TaskClassification(
            task_type=TaskType.FACTUAL_LOOKUP,
            confidence=0.80,
            stage="rules",
            reason="factual question pattern detected",
        )

    # Creative writing
    if _CREATIVE_PATTERNS.search(msg):
        return TaskClassification(
            task_type=TaskType.CREATIVE,
            confidence=0.75,
            stage="rules",
            reason="creative writing pattern detected",
        )

    # Short conversational (no tools, short message, not first turn)
    if not has_tools and len(msg) <= 200 and turn_number > 1:
        return TaskClassification(
            task_type=TaskType.CONVERSATIONAL,
            confidence=0.70,
            stage="rules",
            reason=f"short follow-up ({len(msg)} chars, turn {turn_number})",
        )

    return None  # Not confident enough — fall through to Stage 2


# ---------------------------------------------------------------------------
# Stage 2: Keyword-vector classification
# ---------------------------------------------------------------------------

# Pre-defined keyword vectors per task type (TF-IDF-like weights).
# These represent the "centroid" of each task type in keyword space.
_KEYWORD_VECTORS: dict[TaskType, dict[str, float]] = {
    TaskType.TRIVIAL: {
        "hi": 2.0, "hello": 2.0, "hey": 2.0, "thanks": 2.0, "ok": 2.0,
        "yes": 1.5, "no": 1.5, "sure": 1.5, "cool": 1.5, "great": 1.5,
        "bye": 2.0, "welcome": 1.5, "perfect": 1.5,
    },
    TaskType.CONVERSATIONAL: {
        "what": 1.0, "how": 1.0, "why": 1.0, "can": 0.8, "could": 0.8,
        "would": 0.8, "should": 0.8, "tell": 0.8, "help": 0.8,
        "question": 1.0, "about": 0.5, "think": 0.8, "mean": 0.8,
    },
    TaskType.FACTUAL_LOOKUP: {
        "what": 1.5, "who": 1.5, "when": 1.5, "where": 1.5, "which": 1.5,
        "define": 2.0, "definition": 2.0, "meaning": 2.0, "difference": 1.5,
        "between": 1.0, "list": 1.5, "name": 1.0, "many": 1.5,
    },
    TaskType.SUMMARIZATION: {
        "summarize": 3.0, "summarise": 3.0, "summary": 3.0, "tldr": 3.0,
        "brief": 2.0, "overview": 2.0, "recap": 2.5, "condense": 2.5,
        "shorten": 2.0, "key": 1.0, "points": 1.5, "highlights": 2.0,
    },
    TaskType.CODE_GENERATION: {
        "write": 1.5, "create": 1.5, "implement": 2.0, "build": 1.5,
        "function": 2.0, "class": 2.0, "method": 2.0, "code": 2.0,
        "script": 2.0, "module": 1.5, "api": 1.5, "endpoint": 1.5,
        "test": 1.5, "component": 1.5, "program": 1.5, "generate": 1.5,
        "add": 1.0, "feature": 1.0, "file": 1.5, "save": 1.5,
    },
    TaskType.CODE_REVIEW: {
        "review": 2.5, "explain": 2.0, "debug": 2.5, "bug": 2.5,
        "error": 2.0, "wrong": 2.0, "fix": 2.0, "issue": 1.5,
        "trace": 2.0, "walk": 1.5, "through": 1.0, "understand": 1.5,
        "code": 1.5, "function": 1.0, "does": 1.0, "work": 1.0,
    },
    TaskType.ANALYSIS: {
        "design": 2.5, "architect": 2.5, "analyze": 2.5, "analyse": 2.5,
        "compare": 2.0, "evaluate": 2.0, "plan": 2.0, "strategy": 2.0,
        "tradeoff": 2.5, "optimize": 2.0, "optimise": 2.0, "critique": 2.0,
        "improve": 1.5, "research": 2.0, "investigate": 2.0, "deep": 1.5,
        "pros": 2.0, "cons": 2.0, "approach": 1.5, "architecture": 2.0,
    },
    TaskType.CREATIVE: {
        "write": 1.5, "draft": 2.5, "compose": 2.5, "brainstorm": 2.5,
        "blog": 2.5, "article": 2.5, "essay": 2.5, "story": 2.5,
        "email": 2.0, "message": 1.5, "letter": 2.0, "proposal": 2.0,
        "pitch": 2.0, "presentation": 2.0, "ideas": 2.0, "creative": 2.0,
    },
}

# Pre-compute norms for cosine similarity
_VECTOR_NORMS: dict[TaskType, float] = {}
for _tt, _vec in _KEYWORD_VECTORS.items():
    _VECTOR_NORMS[_tt] = math.sqrt(sum(v * v for v in _vec.values()))


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"[a-z]+", text.lower())


def _cosine_similarity(tokens: list[str], task_type: TaskType) -> float:
    """Compute cosine similarity between token bag and task type keyword vector."""
    vec = _KEYWORD_VECTORS[task_type]
    norm = _VECTOR_NORMS[task_type]
    if norm == 0:
        return 0.0

    # Build token frequency vector
    token_freq: dict[str, int] = {}
    for t in tokens:
        token_freq[t] = token_freq.get(t, 0) + 1

    # Dot product
    dot = 0.0
    for word, weight in vec.items():
        if word in token_freq:
            dot += weight * token_freq[word]

    if dot == 0:
        return 0.0

    # Token vector norm
    token_norm = math.sqrt(sum(f * f for f in token_freq.values()))
    if token_norm == 0:
        return 0.0

    return dot / (norm * token_norm)


def classify_stage2(
    user_message: str,
    *,
    query_embedding: list[float] | None = None,
    task_embedding_index: Any | None = None,
) -> TaskClassification:
    """Stage 2: Semantic embedding or keyword-vector classification.

    When ``query_embedding`` and a ready ``task_embedding_index`` are provided,
    uses real dense embeddings from Ollama.  Otherwise falls back to the
    keyword-vector heuristic.  Always returns a result.
    """
    # Embedding path — real semantic classification
    if (
        query_embedding is not None
        and task_embedding_index is not None
        and getattr(task_embedding_index, "is_ready", False)
    ):
        task_type_str, similarity = task_embedding_index.classify(query_embedding)
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.CONVERSATIONAL

        # If similarity is too low, fall through to keyword vectors
        if similarity >= 0.3:
            confidence = min(0.90, 0.5 + similarity * 0.5)
            return TaskClassification(
                task_type=task_type,
                confidence=confidence,
                stage="embeddings",
                reason=f"embedding similarity ({similarity:.3f}) → {task_type.value}",
            )

    # Keyword-vector fallback
    tokens = _tokenize(user_message)
    if not tokens:
        return TaskClassification(
            task_type=TaskType.CONVERSATIONAL,
            confidence=0.3,
            stage="keywords",
            reason="empty/unparseable message",
        )

    best_type = TaskType.CONVERSATIONAL
    best_score = 0.0

    for task_type_iter in TaskType:
        if task_type_iter == TaskType.TOOL_CONTINUATION:
            continue  # Only classified by rules (iteration > 0)
        score = _cosine_similarity(tokens, task_type_iter)
        if score > best_score:
            best_score = score
            best_type = task_type_iter

    # Map raw cosine similarity to confidence (0.4–0.85 range)
    confidence = min(0.85, 0.4 + best_score * 0.6)

    return TaskClassification(
        task_type=best_type,
        confidence=confidence,
        stage="keywords",
        reason=f"keyword similarity ({best_score:.3f}) → {best_type.value}",
    )


# ---------------------------------------------------------------------------
# Stage 3: LLM classification (async, requires provider)
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT = """\
Classify the following user message into exactly one task type.

Task types:
- trivial: Greetings, acknowledgements, yes/no answers
- conversational: Short Q&A, clarifications, general chat
- factual_lookup: Simple factual questions
- summarization: Requests to summarise or condense text
- code_generation: Writing, creating, or editing code
- code_review: Reviewing, explaining, or debugging code
- analysis: Complex reasoning, planning, design, architecture
- creative: Writing prose, brainstorming, content creation

Respond with ONLY a JSON object:
{{"task_type": "<type>", "confidence": <0.0-1.0>}}

User message:
{message}"""


def build_stage3_prompt(user_message: str) -> str:
    """Build the LLM classification prompt."""
    return _CLASSIFICATION_PROMPT.format(message=user_message[:2000])


def parse_stage3_response(response_text: str) -> TaskClassification:
    """Parse the LLM classification response."""
    import json

    text = response_text.strip()
    # Extract JSON from possible markdown code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    try:
        data = json.loads(text)
        task_type_str = data.get("task_type", "conversational")
        confidence = float(data.get("confidence", 0.7))

        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.CONVERSATIONAL
            confidence = 0.5

        return TaskClassification(
            task_type=task_type,
            confidence=min(1.0, max(0.0, confidence)),
            stage="llm",
            reason=f"LLM classified as {task_type.value}",
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return TaskClassification(
            task_type=TaskType.CONVERSATIONAL,
            confidence=0.4,
            stage="llm",
            reason="LLM response unparseable, defaulting to conversational",
        )


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------

def classify_task(
    *,
    user_message: str,
    has_tools: bool,
    turn_iteration: int,
    turn_number: int,
    complexity_keywords: list[str],
    strategy: str = "rules+keywords",
    confidence_threshold_stage1: float = 0.75,
    confidence_threshold_stage2: float = 0.60,
    query_embedding: list[float] | None = None,
    task_embedding_index: Any | None = None,
) -> TaskClassification:
    """Run the classification pipeline up to the configured strategy depth.

    Args:
        strategy: One of "rules", "rules+keywords", "rules+keywords+llm".
            Note: "rules+keywords+llm" still returns after stage 2 — the caller
            must invoke the async LLM stage separately if confidence is low.
        query_embedding: Pre-computed dense embedding of the user message (from
            Ollama). When provided alongside ``task_embedding_index``, Stage 2
            uses real semantic matching instead of keyword vectors.
        task_embedding_index: A ``TaskEmbeddingIndex`` instance (or any object
            with ``classify(embedding)`` and ``is_ready``).

    Returns:
        Best classification found within the sync stages.
    """
    # Stage 1: Rules
    result = classify_stage1(
        user_message=user_message,
        has_tools=has_tools,
        turn_iteration=turn_iteration,
        turn_number=turn_number,
        complexity_keywords=complexity_keywords,
    )
    if result is not None and result.confidence >= confidence_threshold_stage1:
        return result

    if strategy == "rules":
        # Rules-only mode — return best rule match or default
        return result or TaskClassification(
            task_type=TaskType.CONVERSATIONAL,
            confidence=0.5,
            stage="rules",
            reason="no rule matched, default to conversational",
        )

    # Stage 2: Embeddings (when available) or keyword vectors
    stage2_result = classify_stage2(
        user_message,
        query_embedding=query_embedding,
        task_embedding_index=task_embedding_index,
    )

    # If stage 1 had a result but low confidence, pick the higher-confidence one
    if result is not None:
        if result.confidence >= stage2_result.confidence:
            return result

    if stage2_result.confidence >= confidence_threshold_stage2:
        return stage2_result

    # If neither stage is confident enough, return stage 2 result anyway
    # (caller can check confidence and invoke stage 3 LLM if needed)
    return stage2_result
