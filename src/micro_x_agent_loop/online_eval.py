"""Online eval harness — LLM-judge scoring of historical sessions (Phase 6).

A scheduled job (broker / CLI) samples recent sessions, reconstructs each as a
step-through timeline (reusing ``session_replay``), and asks an LLM judge to
score it against a rubric. Results land in the ``eval_results`` table joined to
``session_id`` (+ ``turn_number``); the aggregate score also back-fills
``routing_outcomes.quality_signal`` (declared but previously never written).

The judge is an injected ``Callable[[str], str]`` so the harness is testable
with a fake judge and provider-agnostic in production.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from loguru import logger

from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.session_replay import reconstruct_session

DEFAULT_RUBRIC = (
    "Score the agent's session from 0.0 (poor) to 1.0 (excellent) on: correctness, "
    "efficiency (avoided wasted tool calls / retries), and appropriate routing. "
    "Respond with a JSON object: {\"score\": <0..1>, \"rationale\": \"<one sentence>\"}."
)

JudgeFn = Callable[[str], str]

_SCORE_RE = re.compile(r'"score"\s*:\s*([0-9]*\.?[0-9]+)')


@dataclass(frozen=True)
class EvalResult:
    session_id: str
    turn_number: int
    score: float
    rubric: str
    rationale: str
    judge_model: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_judgement(text: str) -> tuple[float, str]:
    """Extract (score in [0,1], rationale) from a judge response, defensively."""
    score = 0.0
    rationale = ""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            score = float(obj.get("score", 0.0))
            rationale = str(obj.get("rationale", ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        m = _SCORE_RE.search(text)
        if m:
            score = float(m.group(1))
        rationale = text.strip()[:300]
    return max(0.0, min(1.0, score)), rationale


def build_judge_prompt(timeline: list[str], rubric: str) -> str:
    return f"{rubric}\n\n--- SESSION TIMELINE ---\n" + "\n".join(timeline)


def run_session_eval(
    store: MemoryStore,
    judge: JudgeFn,
    session_id: str,
    *,
    rubric: str = DEFAULT_RUBRIC,
    judge_model: str = "unknown",
    quality_signal_store: object | None = None,
) -> EvalResult:
    """Judge one session and persist the result. Returns the ``EvalResult``.

    ``quality_signal_store`` (a ``RoutingFeedbackStore``, optional) is back-filled:
    score ≥ 0.6 → +1, ≤ 0.4 → -1, else 0, on the session's last turn.
    """
    timeline = reconstruct_session(store, session_id)
    response = judge(build_judge_prompt(timeline, rubric))
    score, rationale = parse_judgement(response)

    turn_number = _last_turn(store, session_id)
    result = EvalResult(session_id, turn_number, score, rubric, rationale, judge_model)
    store.execute(
        "INSERT INTO eval_results (id, session_id, turn_number, score, rubric, rationale, judge_model, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid4()), session_id, turn_number, score, rubric, rationale, judge_model, _utc_now()),
    )
    store.commit()

    if quality_signal_store is not None:
        signal = 1 if score >= 0.6 else (-1 if score <= 0.4 else 0)
        try:
            quality_signal_store.update_quality_signal(session_id, turn_number, signal)  # type: ignore[attr-defined]
        except Exception as ex:
            logger.warning(f"quality_signal back-fill failed: {ex}")

    return result


def _last_turn(store: MemoryStore, session_id: str) -> int:
    row = store.execute(
        "SELECT payload_json FROM events WHERE session_id = ? AND type = 'metric.api_call' ORDER BY rowid DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(json.loads(row["payload_json"]).get("turn_number", 0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0


def sample_recent_sessions(store: MemoryStore, limit: int = 10) -> list[str]:
    """Return up to *limit* most-recently-updated session ids (the eval sampling set)."""
    rows = store.execute(
        "SELECT id FROM sessions ORDER BY updated_at DESC, created_at DESC LIMIT ?",
        (max(1, limit),),
    ).fetchall()
    return [r["id"] for r in rows]
