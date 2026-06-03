"""Rolling-window alerting over observability metrics (PLAN-observability Phase 5).

Config (``ObservabilityAlerts``): a list of ``{metric, threshold, window, channel}``
rules. After each ``metric.api_call`` the most recent ``window`` events are scanned
and any breached rule notifies its channel. Channel adapters mirror the spirit of
``broker/channels.py`` (log + webhook); the evaluator itself is a pure function so
it is testable without I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from micro_x_agent_loop.memory.store import MemoryStore

# metric -> comparison direction. "above" fires when value > threshold.
_DIRECTION: dict[str, str] = {
    "cost_window": "above",
    "error_rate": "above",
    "turn_cap_trips": "above",
    "avg_confidence": "below",
    "cache_hit_rate": "below",
}


@dataclass(frozen=True)
class AlertRule:
    metric: str
    threshold: float
    window: int
    channel: str
    direction: str

    @staticmethod
    def from_config(raw: dict) -> AlertRule | None:
        metric = str(raw.get("metric", "")).strip()
        if metric not in _DIRECTION:
            logger.warning(f"ObservabilityAlerts: unknown metric {metric!r} — ignoring rule")
            return None
        return AlertRule(
            metric=metric,
            threshold=float(raw.get("threshold", 0.0)),
            window=int(raw.get("window", 50)),
            channel=str(raw.get("channel", "log")),
            direction=str(raw.get("direction", _DIRECTION[metric])),
        )


@dataclass(frozen=True)
class Alert:
    rule: AlertRule
    value: float
    message: str


def _compute_metric(metric: str, events: list[dict]) -> float | None:
    """Compute *metric* over *events* (each ``{type, payload}``). None if not computable."""
    api = [e["payload"] for e in events if e.get("type") == "metric.api_call"]
    errors = [e for e in events if e.get("type") == "metric.api_call_error"]

    if metric == "cost_window":
        return sum(float(p.get("estimated_cost_usd", 0) or 0) for p in api)
    if metric == "error_rate":
        total = len(api) + len(errors)
        return (len(errors) / total) if total else None
    if metric == "turn_cap_trips":
        return float(sum(1 for e in events if e.get("type") == "turn.cap_reached"))
    if metric == "avg_confidence":
        confs = [
            float(e["payload"].get("confidence", 0) or 0)
            for e in events
            if e.get("type") == "routing.decision"
        ]
        return (sum(confs) / len(confs)) if confs else None
    if metric == "cache_hit_rate":
        cache = sum(float(p.get("cache_read_input_tokens", 0) or 0) for p in api)
        fresh = sum(float(p.get("input_tokens", 0) or 0) for p in api)
        denom = cache + fresh
        return (cache / denom) if denom else None
    return None


def _breached(value: float, rule: AlertRule) -> bool:
    return value > rule.threshold if rule.direction == "above" else value < rule.threshold


def evaluate_alerts(events: list[dict], rules: list[AlertRule]) -> list[Alert]:
    """Pure evaluation: return the alerts breached by the current *events* window."""
    fired: list[Alert] = []
    for rule in rules:
        window_events = events[-rule.window :] if rule.window > 0 else events
        value = _compute_metric(rule.metric, window_events)
        if value is None:
            continue
        if _breached(value, rule):
            fired.append(
                Alert(
                    rule=rule,
                    value=value,
                    message=(
                        f"[observability-alert] {rule.metric}={value:.4f} "
                        f"{'>' if rule.direction == 'above' else '<'} {rule.threshold} "
                        f"(window={rule.window}) → {rule.channel}"
                    ),
                )
            )
    return fired


def _notify(alert: Alert) -> None:
    """Dispatch an alert to its channel. ``log`` (default) or ``webhook:<url>``."""
    channel = alert.rule.channel
    if channel.startswith("webhook:"):
        url = channel.split(":", 1)[1]
        try:
            import httpx

            httpx.post(url, json={"text": alert.message}, timeout=5.0)
        except Exception as ex:
            logger.warning(f"Alert webhook failed ({url}): {ex}")
    else:
        logger.warning(alert.message)


def build_alert_subscriber(
    rules_config: list[Any],
    store: MemoryStore,
    *,
    notifier: Callable[[Alert], None] = _notify,
) -> Callable[[str, dict], None] | None:
    """Build an ObservabilityEmitter subscriber that evaluates alert rules.

    Rules are checked after each ``metric.api_call``. Each rule de-dupes against
    its own last-fired state so a sustained breach notifies once, not per event.
    """
    rules = [r for raw in rules_config if isinstance(raw, dict) and (r := AlertRule.from_config(raw)) is not None]
    if not rules:
        return None

    last_state: dict[str, bool] = {}

    def _subscriber(event_type: str, payload: dict) -> None:
        if event_type != "metric.api_call":
            return
        session_id = payload.get("session_id", "")
        rows = store.execute(
            "SELECT type, payload_json FROM events WHERE session_id = ? ORDER BY rowid DESC LIMIT 500",
            (session_id,),
        ).fetchall()
        import json

        events = [{"type": r["type"], "payload": json.loads(r["payload_json"])} for r in reversed(rows)]
        for alert in evaluate_alerts(events, rules):
            key = f"{alert.rule.metric}:{alert.rule.channel}"
            if not last_state.get(key, False):  # edge-triggered: only on transition into breach
                notifier(alert)
            last_state[key] = True
        # Clear de-dupe state for rules that are no longer breaching.
        fired_keys = {f"{a.rule.metric}:{a.rule.channel}" for a in evaluate_alerts(events, rules)}
        for rule in rules:
            key = f"{rule.metric}:{rule.channel}"
            if key not in fired_keys:
                last_state[key] = False

    return _subscriber
