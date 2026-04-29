"""CLI module for analysing metrics.jsonl files.

Usage:
    python -m micro_x_agent_loop.analyze_costs [OPTIONS]

Options:
    --file PATH        Path to metrics.jsonl (default: metrics.jsonl)
    --session ID       Filter to a specific session ID
    --since DATETIME   Only include records after this ISO timestamp
    --compare A B      Compare two session IDs side-by-side
    --csv              Output as CSV instead of table
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _load_records(path: str, session_id: str | None = None, since: str | None = None) -> list[dict]:
    records: list[dict] = []
    since_ts: float | None = None
    if since:
        dt = datetime.fromisoformat(since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        since_ts = dt.timestamp()

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id and record.get("session_id") != session_id:
                continue
            if since_ts and record.get("timestamp", 0) < since_ts:
                continue
            records.append(record)
    return records


def _aggregate(records: list[dict]) -> dict:
    agg: dict = {
        "api_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_create_tokens": 0,
        "total_cost_usd": 0.0,
        "total_duration_ms": 0.0,
        "tool_calls": 0,
        "tool_errors": 0,
        "compaction_events": 0,
        "compaction_tokens_freed": 0,
        "tool_counts": {},
    }

    for r in records:
        rtype = r.get("type")
        if rtype == "api_call":
            agg["api_calls"] += 1
            agg["total_input_tokens"] += r.get("input_tokens", 0)
            agg["total_output_tokens"] += r.get("output_tokens", 0)
            agg["total_cache_read_tokens"] += r.get("cache_read_input_tokens", 0)
            agg["total_cache_create_tokens"] += r.get("cache_creation_input_tokens", 0)
            agg["total_cost_usd"] += r.get("estimated_cost_usd", 0)
            agg["total_duration_ms"] += r.get("duration_ms", 0)
        elif rtype == "tool_execution":
            agg["tool_calls"] += 1
            if r.get("is_error"):
                agg["tool_errors"] += 1
            name = r.get("tool_name", "unknown")
            agg["tool_counts"][name] = agg["tool_counts"].get(name, 0) + 1
        elif rtype == "compaction":
            agg["compaction_events"] += 1
            agg["compaction_tokens_freed"] += r.get("tokens_freed", 0)

    return agg


def _print_table(agg: dict, label: str = "") -> None:
    if label:
        print(f"\n=== {label} ===")
    print(f"API calls:            {agg['api_calls']}")
    print(f"Input tokens:         {agg['total_input_tokens']:,}")
    print(f"Output tokens:        {agg['total_output_tokens']:,}")
    print(f"Cache read tokens:    {agg['total_cache_read_tokens']:,}")
    print(f"Cache create tokens:  {agg['total_cache_create_tokens']:,}")
    print(f"Total cost (USD):     ${agg['total_cost_usd']:.6f}")
    print(f"Total duration:       {agg['total_duration_ms']:,.0f} ms")
    print(f"Tool calls:           {agg['tool_calls']} ({agg['tool_errors']} errors)")
    print(f"Compaction events:    {agg['compaction_events']}")
    print(f"Tokens freed:         {agg['compaction_tokens_freed']:,}")
    if agg["tool_counts"]:
        print("Tool breakdown:")
        for name, count in sorted(agg["tool_counts"].items(), key=lambda x: -x[1]):
            print(f"  {name}: {count}")


def _print_csv(agg: dict, label: str = "") -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(
        [
            "label",
            "api_calls",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_create_tokens",
            "cost_usd",
            "duration_ms",
            "tool_calls",
            "tool_errors",
            "compaction_events",
            "tokens_freed",
        ]
    )
    writer.writerow(
        [
            label,
            agg["api_calls"],
            agg["total_input_tokens"],
            agg["total_output_tokens"],
            agg["total_cache_read_tokens"],
            agg["total_cache_create_tokens"],
            f"{agg['total_cost_usd']:.6f}",
            f"{agg['total_duration_ms']:.0f}",
            agg["tool_calls"],
            agg["tool_errors"],
            agg["compaction_events"],
            agg["compaction_tokens_freed"],
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze agent cost metrics")
    parser.add_argument("--file", default="metrics.jsonl", help="Path to metrics.jsonl")
    parser.add_argument("--session", default=None, help="Filter to session ID")
    parser.add_argument("--since", default=None, help="Only include records after ISO timestamp")
    parser.add_argument("--compare", nargs=2, metavar=("SESSION_A", "SESSION_B"), help="Compare two session IDs")
    parser.add_argument("--csv", action="store_true", help="Output as CSV")
    args = parser.parse_args()

    path = args.file
    if not Path(path).exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    if args.compare:
        session_a, session_b = args.compare
        records_a = _load_records(path, session_id=session_a, since=args.since)
        records_b = _load_records(path, session_id=session_b, since=args.since)
        agg_a = _aggregate(records_a)
        agg_b = _aggregate(records_b)
        if args.csv:
            _print_csv(agg_a, label=session_a)
            _print_csv(agg_b, label=session_b)
        else:
            _print_table(agg_a, label=f"Session {session_a}")
            _print_table(agg_b, label=f"Session {session_b}")
            # Delta
            print("\n=== Delta (B - A) ===")
            cost_delta = agg_b["total_cost_usd"] - agg_a["total_cost_usd"]
            token_delta = (agg_b["total_input_tokens"] + agg_b["total_output_tokens"]) - (
                agg_a["total_input_tokens"] + agg_a["total_output_tokens"]
            )
            print(f"Cost delta:   ${cost_delta:+.6f}")
            print(f"Token delta:  {token_delta:+,}")
    else:
        records = _load_records(path, session_id=args.session, since=args.since)
        agg = _aggregate(records)
        label = args.session or "all"
        if args.csv:
            _print_csv(agg, label=label)
        else:
            _print_table(agg, label=label)


if __name__ == "__main__":
    main()
