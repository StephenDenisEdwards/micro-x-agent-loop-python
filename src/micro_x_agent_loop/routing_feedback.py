"""Routing feedback collection and adaptive routing.

Collects per-turn routing outcomes (cost, latency, quality signals)
and stores them in SQLite for analysis. Provides adaptive threshold
adjustment based on historical accuracy.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoutingOutcome:
    """A single routing outcome record."""

    session_id: str
    turn_number: int
    task_type: str
    provider: str
    model: str
    cost_usd: float
    latency_ms: float
    stage: str  # "rules", "keywords", "llm"
    confidence: float
    quality_signal: int = 0  # -1 = negative, 0 = neutral, +1 = positive
    timestamp: float = 0.0


class RoutingFeedbackStore:
    """SQLite-backed store for routing outcomes."""

    _CREATE_TABLE = """\
    CREATE TABLE IF NOT EXISTS routing_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        task_type TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        cost_usd REAL NOT NULL,
        latency_ms REAL NOT NULL,
        stage TEXT NOT NULL,
        confidence REAL NOT NULL,
        quality_signal INTEGER NOT NULL DEFAULT 0,
        timestamp REAL NOT NULL
    )"""

    _CREATE_INDEX = """\
    CREATE INDEX IF NOT EXISTS idx_routing_task_type
    ON routing_outcomes (task_type)"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute(self._CREATE_TABLE)
            self._conn.execute(self._CREATE_INDEX)
            self._conn.commit()
        return self._conn

    def record(self, outcome: RoutingOutcome) -> None:
        """Record a routing outcome."""
        conn = self._ensure_connection()
        conn.execute(
            "INSERT INTO routing_outcomes "
            "(session_id, turn_number, task_type, provider, model, "
            "cost_usd, latency_ms, stage, confidence, quality_signal, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                outcome.session_id,
                outcome.turn_number,
                outcome.task_type,
                outcome.provider,
                outcome.model,
                outcome.cost_usd,
                outcome.latency_ms,
                outcome.stage,
                outcome.confidence,
                outcome.quality_signal,
                outcome.timestamp or time.time(),
            ),
        )
        conn.commit()

    def update_quality_signal(
        self, session_id: str, turn_number: int, signal: int
    ) -> None:
        """Update the quality signal for a specific turn's routing outcome."""
        conn = self._ensure_connection()
        conn.execute(
            "UPDATE routing_outcomes SET quality_signal = ? "
            "WHERE session_id = ? AND turn_number = ?",
            (signal, session_id, turn_number),
        )
        conn.commit()

    def get_task_type_stats(self) -> list[dict]:
        """Get aggregated statistics per task type."""
        conn = self._ensure_connection()
        rows = conn.execute(
            "SELECT task_type, "
            "COUNT(*) as total, "
            "AVG(cost_usd) as avg_cost, "
            "AVG(latency_ms) as avg_latency, "
            "AVG(confidence) as avg_confidence, "
            "SUM(CASE WHEN quality_signal > 0 THEN 1 ELSE 0 END) as positive, "
            "SUM(CASE WHEN quality_signal < 0 THEN 1 ELSE 0 END) as negative, "
            "SUM(cost_usd) as total_cost "
            "FROM routing_outcomes "
            "GROUP BY task_type "
            "ORDER BY total DESC"
        ).fetchall()

        return [
            {
                "task_type": row[0],
                "total": row[1],
                "avg_cost": row[2],
                "avg_latency": row[3],
                "avg_confidence": row[4],
                "positive_signals": row[5],
                "negative_signals": row[6],
                "total_cost": row[7],
            }
            for row in rows
        ]

    def get_provider_stats(self) -> list[dict]:
        """Get aggregated statistics per provider."""
        conn = self._ensure_connection()
        rows = conn.execute(
            "SELECT provider, "
            "COUNT(*) as total, "
            "AVG(cost_usd) as avg_cost, "
            "AVG(latency_ms) as avg_latency, "
            "SUM(CASE WHEN quality_signal < 0 THEN 1 ELSE 0 END) as errors, "
            "SUM(cost_usd) as total_cost "
            "FROM routing_outcomes "
            "GROUP BY provider "
            "ORDER BY total DESC"
        ).fetchall()

        return [
            {
                "provider": row[0],
                "total": row[1],
                "avg_cost": row[2],
                "avg_latency": row[3],
                "errors": row[4],
                "total_cost": row[5],
            }
            for row in rows
        ]

    def get_stage_stats(self) -> list[dict]:
        """Get aggregated statistics per classification stage."""
        conn = self._ensure_connection()
        rows = conn.execute(
            "SELECT stage, "
            "COUNT(*) as total, "
            "AVG(confidence) as avg_confidence, "
            "ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM routing_outcomes), 1) as pct "
            "FROM routing_outcomes "
            "GROUP BY stage "
            "ORDER BY total DESC"
        ).fetchall()

        return [
            {
                "stage": row[0],
                "total": row[1],
                "avg_confidence": row[2],
                "percentage": row[3],
            }
            for row in rows
        ]

    def get_recent_outcomes(self, limit: int = 20) -> list[dict]:
        """Get the most recent routing outcomes."""
        conn = self._ensure_connection()
        rows = conn.execute(
            "SELECT session_id, turn_number, task_type, provider, model, "
            "cost_usd, latency_ms, stage, confidence, quality_signal, timestamp "
            "FROM routing_outcomes ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [
            {
                "session_id": row[0],
                "turn_number": row[1],
                "task_type": row[2],
                "provider": row[3],
                "model": row[4],
                "cost_usd": row[5],
                "latency_ms": row[6],
                "stage": row[7],
                "confidence": row[8],
                "quality_signal": row[9],
                "timestamp": row[10],
            }
            for row in rows
        ]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
