"""Cost reconciliation — compare our estimated costs against Anthropic's billing API.

Queries the anthropic-admin MCP tool for actual billed costs and compares
them to our locally tracked metric.api_call events in the SQLite events table.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from loguru import logger

from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.tool import Tool


RECONCILE_TOOL_NAME = "anthropic-admin__anthropic_usage"
DIVERGENCE_THRESHOLD_PCT = 5.0


def _format_date(dt: datetime) -> str:
    """Format datetime as RFC 3339 for Anthropic API."""
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def _load_local_costs(
    store: MemoryStore,
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, float]]:
    """Load metric.api_call events from SQLite, grouped by date and model.

    Returns: {date_str: {model: total_cost_usd}}
    """
    rows = store.execute(
        """
        SELECT payload_json FROM events
        WHERE type = 'metric.api_call'
        AND created_at >= ? AND created_at < ?
        ORDER BY created_at
        """,
        (start_date, end_date),
    ).fetchall()

    by_date_model: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            continue

        ts = payload.get("timestamp")
        if not ts:
            continue
        dt = datetime.fromtimestamp(ts, tz=UTC)
        date_str = dt.strftime("%Y-%m-%d")
        model = payload.get("model", "unknown")
        cost = payload.get("estimated_cost_usd", 0.0)
        by_date_model[date_str][model] += cost

    return dict(by_date_model)


def _extract_records(response_text: str) -> list[dict]:
    """Extract the data records list from an Anthropic API response."""
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse Anthropic response as JSON")
        return []

    # MCP server wraps in "Cost Report:\n{json}" — strip the prefix if present
    if isinstance(data, str):
        for prefix in ("Cost Report:\n", "Token Usage Report:\n"):
            if data.startswith(prefix):
                data = data[len(prefix):]
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return []

    report_data = data.get("data", data) if isinstance(data, dict) else data
    return report_data if isinstance(report_data, list) else []


def _bucket_date(record: dict) -> str:
    """Extract YYYY-MM-DD from a bucket record."""
    bucket = record.get("bucket_start_time", record.get("bucket_start_date", ""))
    return bucket[:10] if bucket else ""


def _parse_cost_report(response_text: str) -> dict[str, float]:
    """Parse cost report into {date: total_cost_usd}.

    The cost report does NOT support group_by model — it returns aggregate
    daily costs only.
    """
    by_date: dict[str, float] = defaultdict(float)
    for record in _extract_records(response_text):
        date_str = _bucket_date(record)
        cost = record.get("amount_usd", record.get("amount", 0.0))
        if isinstance(cost, (int, float)):
            by_date[date_str] += cost
    return dict(by_date)


def _parse_usage_report_to_costs(response_text: str) -> dict[str, dict[str, float]]:
    """Parse usage report (grouped by model) and estimate costs from token counts.

    Returns: {date: {model: estimated_cost_usd}}

    We import the pricing lookup at call time to avoid circular imports.
    """
    from micro_x_agent_loop.usage import UsageResult, estimate_cost

    by_date_model: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for record in _extract_records(response_text):
        date_str = _bucket_date(record)
        model = record.get("model", "unknown")
        input_tokens = int(record.get("input_tokens", 0))
        output_tokens = int(record.get("output_tokens", 0))
        cache_read = int(record.get("cache_read_input_tokens", 0))
        cache_create = int(record.get("cache_creation_input_tokens", 0))

        usage = UsageResult(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_create,
            provider="anthropic",
            model=model,
        )
        by_date_model[date_str][model] += estimate_cost(usage)
    return dict(by_date_model)


def _shorten_model(model: str) -> str:
    """Shorten model name for display."""
    for prefix in ("claude-", "anthropic/claude-"):
        if model.startswith(prefix):
            model = model[len(prefix):]
    return model


def _divergence(ours: float, theirs: float) -> tuple[float, str]:
    """Calculate divergence percentage and status label."""
    if theirs > 0:
        diff_pct = abs(ours - theirs) / theirs * 100
    elif ours > 0:
        diff_pct = 100.0
    else:
        diff_pct = 0.0
    status = "MISMATCH" if diff_pct > DIVERGENCE_THRESHOLD_PCT else "OK"
    return diff_pct, status


def _build_model_report(
    lines: list[str],
    local_costs: dict[str, dict[str, float]],
    anthropic_costs: dict[str, dict[str, float]],
    local_total: float,
    anthropic_total: float,
) -> None:
    """Build a per-date, per-model comparison table."""
    all_dates = sorted(set(list(local_costs.keys()) + list(anthropic_costs.keys())))

    lines.append("")
    header = f"{'Date':<12} {'Model':<35} {'Ours':>10} {'Anthropic':>10} {'Diff':>8} {'Status'}"
    lines.append(header)
    lines.append("-" * len(header))

    mismatches = 0
    for date in all_dates:
        local_by_model = local_costs.get(date, {})
        anthropic_by_model = anthropic_costs.get(date, {})
        date_models = sorted(set(list(local_by_model.keys()) + list(anthropic_by_model.keys())))

        for model in date_models:
            ours = local_by_model.get(model, 0.0)
            theirs = anthropic_by_model.get(model, 0.0)
            diff_pct, status = _divergence(ours, theirs)
            if status == "MISMATCH":
                mismatches += 1

            lines.append(
                f"{date:<12} {_shorten_model(model):<35} ${ours:>9.4f} ${theirs:>9.4f} {diff_pct:>6.1f}%  {status}"
            )

    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<12} {'':<35} ${local_total:>9.4f} ${anthropic_total:>9.4f}")
    _append_summary(lines, local_total, anthropic_total, mismatches)


def _build_daily_report(
    lines: list[str],
    local_costs: dict[str, dict[str, float]],
    anthropic_daily: dict[str, float],
    local_total: float,
    anthropic_total: float,
) -> None:
    """Build a per-date aggregate comparison table (no per-model Anthropic data)."""
    # Collapse local per-model into per-date totals
    local_daily: dict[str, float] = {}
    for date, by_model in local_costs.items():
        local_daily[date] = sum(by_model.values())

    all_dates = sorted(set(list(local_daily.keys()) + list(anthropic_daily.keys())))

    lines.append("")
    lines.append("(Per-model Anthropic data unavailable — showing daily aggregates)")
    lines.append("")
    header = f"{'Date':<12} {'Ours':>12} {'Anthropic':>12} {'Diff':>8} {'Status'}"
    lines.append(header)
    lines.append("-" * len(header))

    mismatches = 0
    for date in all_dates:
        ours = local_daily.get(date, 0.0)
        theirs = anthropic_daily.get(date, 0.0)
        diff_pct, status = _divergence(ours, theirs)
        if status == "MISMATCH":
            mismatches += 1
        lines.append(f"{date:<12} ${ours:>11.4f} ${theirs:>11.4f} {diff_pct:>6.1f}%  {status}")

    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<12} ${local_total:>11.4f} ${anthropic_total:>11.4f}")
    _append_summary(lines, local_total, anthropic_total, mismatches)

    # Also show local per-model breakdown for reference
    lines.append("")
    lines.append("Local per-model breakdown:")
    model_totals: dict[str, float] = defaultdict(float)
    for by_model in local_costs.values():
        for model, cost in by_model.items():
            model_totals[model] += cost
    for model, cost in sorted(model_totals.items(), key=lambda x: -x[1]):
        lines.append(f"  {_shorten_model(model):<40} ${cost:>9.4f}")


def _append_summary(
    lines: list[str], local_total: float, anthropic_total: float, mismatches: int
) -> None:
    """Append overall divergence and mismatch summary."""
    if anthropic_total > 0:
        total_diff = abs(local_total - anthropic_total) / anthropic_total * 100
        total_status = "MISMATCH" if total_diff > DIVERGENCE_THRESHOLD_PCT else "OK"
        lines.append(f"Overall divergence: {total_diff:.1f}% — {total_status}")
    elif local_total > 0:
        lines.append("Anthropic reported $0 — cannot calculate divergence.")

    if mismatches > 0:
        lines.append(f"\n{mismatches} date/model combination(s) exceeded {DIVERGENCE_THRESHOLD_PCT}% threshold.")
    else:
        lines.append("\nAll costs within threshold. Pricing table appears accurate.")


def _parse_date(value: str) -> datetime:
    """Parse a YYYY-MM-DD string into a midnight-UTC datetime."""
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


async def reconcile_costs(
    tool_map: dict[str, Tool],
    store: MemoryStore | None,
    days: int = 1,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[str]:
    """Run cost reconciliation and return formatted report lines.

    Args:
        tool_map: Available tools (must include anthropic-admin__anthropic_usage).
        store: SQLite memory store for loading local metric events.
        days: Number of days to look back including today (default: 1 = today only).
              Ignored when start/end are provided.
        start: Optional start date (YYYY-MM-DD). Inclusive.
        end: Optional end date (YYYY-MM-DD). Inclusive.

    Returns:
        List of formatted report lines for display.
    """
    lines: list[str] = []

    # Validate prerequisites
    tool = tool_map.get(RECONCILE_TOOL_NAME)
    if tool is None:
        lines.append("Error: anthropic-admin MCP server not available.")
        lines.append(f"  Tool '{RECONCILE_TOOL_NAME}' not found in tool_map.")
        lines.append("  Ensure the anthropic-admin MCP server is configured and running.")
        return lines

    if store is None:
        lines.append("Error: Memory not enabled — no local cost events to compare.")
        lines.append("  Enable MemoryEnabled=true in config.")
        return lines

    # Date range
    now_midnight = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if start is not None and end is not None:
        start_dt = _parse_date(start)
        end_dt = _parse_date(end) + timedelta(days=1)  # inclusive end
    elif start is not None:
        start_dt = _parse_date(start)
        end_dt = now_midnight + timedelta(days=1)
    elif end is not None:
        end_dt = _parse_date(end) + timedelta(days=1)
        start_dt = end_dt - timedelta(days=days)
    else:
        # Default: last N days including today
        end_dt = now_midnight + timedelta(days=1)
        start_dt = end_dt - timedelta(days=days)

    # Anthropic API rejects end dates beyond today — use separate ranges for
    # local queries (can include today) vs API queries (must end at today's midnight).
    api_end_dt = min(end_dt, now_midnight)
    if api_end_dt <= start_dt:
        # All requested data is from today — API has no data yet, but local does
        api_end_dt = None
    start_str = _format_date(start_dt)
    # Local query uses full range (including today)
    start_date_iso = start_dt.strftime("%Y-%m-%dT00:00:00+00:00")
    end_date_iso = end_dt.strftime("%Y-%m-%dT00:00:00+00:00")

    lines.append(f"Cost Reconciliation: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
    lines.append("-" * 60)

    # 1. Load local costs from events table
    local_costs = _load_local_costs(store, start_date_iso, end_date_iso)
    local_total = sum(cost for by_model in local_costs.values() for cost in by_model.values())

    if not local_costs:
        lines.append("No local metric.api_call events found for this period.")
        lines.append("  (Events are only recorded after the metrics persistence feature was enabled.)")
        return lines

    # 2. Call Anthropic API for actual billed costs
    #    The API rejects end dates in the future, so we clamp to today's midnight.
    #    If all data is from today, we skip the API call entirely.
    anthropic_daily_costs: dict[str, float] = {}
    anthropic_model_costs: dict[str, dict[str, float]] = {}
    anthropic_total = 0.0

    if api_end_dt is not None:
        api_end_str = _format_date(api_end_dt)
        lines.append("Querying Anthropic billing API...")

        # 2a. Cost report — daily aggregate totals
        try:
            cost_result = await tool.execute({
                "action": "cost",
                "starting_at": start_str,
                "ending_at": api_end_str,
                "bucket_width": "1d",
            })
        except Exception as ex:
            lines.append(f"Error calling Anthropic API: {ex}")
            lines.append("  Check that ANTHROPIC_ADMIN_API_KEY is set.")
            return lines

        if cost_result.is_error:
            lines.append(f"Anthropic API error: {cost_result.text}")
            return lines

        # 2b. Usage report — per-model token breakdown
        usage_result = None
        try:
            usage_result = await tool.execute({
                "action": "usage",
                "starting_at": start_str,
                "ending_at": api_end_str,
                "bucket_width": "1d",
                "group_by": ["model"],
            })
        except Exception:
            pass  # Non-fatal — we can still show aggregate comparison

        # 3. Parse responses
        anthropic_daily_costs = _parse_cost_report(cost_result.text)
        anthropic_total = sum(anthropic_daily_costs.values())

        if usage_result is not None and not usage_result.is_error:
            anthropic_model_costs = _parse_usage_report_to_costs(usage_result.text)
    else:
        lines.append("(All data is from today — Anthropic billing data not yet available)")

    # 4. Build comparison report
    if anthropic_model_costs:
        _build_model_report(lines, local_costs, anthropic_model_costs, local_total, anthropic_total)
    else:
        _build_daily_report(lines, local_costs, anthropic_daily_costs, local_total, anthropic_total)

    return lines
