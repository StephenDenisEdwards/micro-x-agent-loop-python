"""Tests for analyze_costs module."""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from micro_x_agent_loop.analyze_costs import (
    _aggregate,
    _load_records,
    _print_csv,
    _print_table,
    main,
)


def _write_jsonl(tmp_dir: str, records: list[dict]) -> str:
    path = str(Path(tmp_dir) / "metrics.jsonl")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


class LoadRecordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_loads_all_records(self) -> None:
        path = _write_jsonl(self._tmp.name, [
            {"type": "api_call", "session_id": "s1"},
            {"type": "tool_execution", "session_id": "s2"},
        ])
        records = _load_records(path)
        self.assertEqual(2, len(records))

    def test_filters_by_session_id(self) -> None:
        path = _write_jsonl(self._tmp.name, [
            {"type": "api_call", "session_id": "s1"},
            {"type": "api_call", "session_id": "s2"},
        ])
        records = _load_records(path, session_id="s1")
        self.assertEqual(1, len(records))
        self.assertEqual("s1", records[0]["session_id"])

    def test_filters_by_since(self) -> None:
        path = _write_jsonl(self._tmp.name, [
            {"type": "api_call", "timestamp": 1000.0},
            {"type": "api_call", "timestamp": 2000.0},
        ])
        records = _load_records(path, since="1970-01-01T00:30:00Z")
        # 30 minutes = 1800 seconds; only the 2000.0 record passes
        self.assertEqual(1, len(records))
        self.assertEqual(2000.0, records[0]["timestamp"])

    def test_since_without_timezone_treated_as_utc(self) -> None:
        path = _write_jsonl(self._tmp.name, [
            {"type": "api_call", "timestamp": 1.0},
            {"type": "api_call", "timestamp": 9999999999.0},
        ])
        records = _load_records(path, since="2000-01-01T00:00:00")
        self.assertEqual(1, len(records))

    def test_skips_empty_lines(self) -> None:
        path = str(Path(self._tmp.name) / "metrics.jsonl")
        with open(path, "w") as f:
            f.write("\n")
            f.write(json.dumps({"type": "api_call"}) + "\n")
            f.write("   \n")
        records = _load_records(path)
        self.assertEqual(1, len(records))

    def test_skips_invalid_json(self) -> None:
        path = str(Path(self._tmp.name) / "metrics.jsonl")
        with open(path, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "api_call"}) + "\n")
        records = _load_records(path)
        self.assertEqual(1, len(records))


class AggregateTests(unittest.TestCase):
    def test_empty(self) -> None:
        agg = _aggregate([])
        self.assertEqual(0, agg["api_calls"])
        self.assertEqual(0, agg["tool_calls"])

    def test_api_call_record(self) -> None:
        records = [{
            "type": "api_call",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
            "estimated_cost_usd": 0.001,
            "duration_ms": 500,
        }]
        agg = _aggregate(records)
        self.assertEqual(1, agg["api_calls"])
        self.assertEqual(100, agg["total_input_tokens"])
        self.assertEqual(50, agg["total_output_tokens"])
        self.assertEqual(10, agg["total_cache_read_tokens"])
        self.assertEqual(5, agg["total_cache_create_tokens"])
        self.assertAlmostEqual(0.001, agg["total_cost_usd"])
        self.assertEqual(500, agg["total_duration_ms"])

    def test_tool_execution_record(self) -> None:
        records = [
            {"type": "tool_execution", "tool_name": "bash", "is_error": False},
            {"type": "tool_execution", "tool_name": "bash", "is_error": True},
        ]
        agg = _aggregate(records)
        self.assertEqual(2, agg["tool_calls"])
        self.assertEqual(1, agg["tool_errors"])
        self.assertEqual({"bash": 2}, agg["tool_counts"])

    def test_compaction_record(self) -> None:
        records = [{"type": "compaction", "tokens_freed": 1000}]
        agg = _aggregate(records)
        self.assertEqual(1, agg["compaction_events"])
        self.assertEqual(1000, agg["compaction_tokens_freed"])

    def test_unknown_type_ignored(self) -> None:
        agg = _aggregate([{"type": "unknown_event"}])
        self.assertEqual(0, agg["api_calls"])
        self.assertEqual(0, agg["tool_calls"])

    def test_multiple_tools(self) -> None:
        records = [
            {"type": "tool_execution", "tool_name": "bash"},
            {"type": "tool_execution", "tool_name": "read"},
            {"type": "tool_execution", "tool_name": "bash"},
        ]
        agg = _aggregate(records)
        self.assertEqual({"bash": 2, "read": 1}, agg["tool_counts"])


class PrintTableTests(unittest.TestCase):
    def _capture(self, agg: dict, label: str = "") -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_table(agg, label=label)
        return buf.getvalue()

    def _empty_agg(self) -> dict:
        return {
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

    def test_prints_basic_stats(self) -> None:
        agg = self._empty_agg()
        agg["api_calls"] = 3
        out = self._capture(agg)
        self.assertIn("API calls:", out)
        self.assertIn("3", out)

    def test_label_printed(self) -> None:
        agg = self._empty_agg()
        out = self._capture(agg, label="Session ABC")
        self.assertIn("Session ABC", out)

    def test_tool_counts_printed(self) -> None:
        agg = self._empty_agg()
        agg["tool_counts"] = {"bash": 5, "read": 2}
        out = self._capture(agg)
        self.assertIn("bash: 5", out)
        self.assertIn("read: 2", out)

    def test_no_label_no_header(self) -> None:
        agg = self._empty_agg()
        out = self._capture(agg)
        self.assertNotIn("===", out)


class PrintCsvTests(unittest.TestCase):
    def _capture_csv(self, agg: dict, label: str = "") -> list[list[str]]:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_csv(agg, label=label)
        buf.seek(0)
        return list(csv.reader(buf))

    def _empty_agg(self) -> dict:
        return {
            "api_calls": 5,
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "total_cache_read_tokens": 10,
            "total_cache_create_tokens": 5,
            "total_cost_usd": 0.002,
            "total_duration_ms": 1000.0,
            "tool_calls": 3,
            "tool_errors": 1,
            "compaction_events": 2,
            "compaction_tokens_freed": 500,
            "tool_counts": {},
        }

    def test_csv_has_header_and_row(self) -> None:
        rows = self._capture_csv(self._empty_agg(), label="session1")
        self.assertEqual(2, len(rows))
        self.assertIn("api_calls", rows[0])
        self.assertEqual("session1", rows[1][0])

    def test_csv_values_correct(self) -> None:
        rows = self._capture_csv(self._empty_agg(), label="s1")
        data_row = rows[1]
        self.assertEqual("5", data_row[1])  # api_calls
        self.assertEqual("100", data_row[2])  # input_tokens


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_file(self, records: list[dict]) -> str:
        return _write_jsonl(self._tmp.name, records)

    def test_file_not_found(self) -> None:
        with patch.object(sys, "argv", ["prog", "--file", "/nonexistent/path.jsonl"]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(1, cm.exception.code)

    def test_basic_table_output(self) -> None:
        path = self._make_file([{"type": "api_call", "input_tokens": 10}])
        buf = io.StringIO()
        with patch.object(sys, "argv", ["prog", "--file", path]):
            with patch("sys.stdout", buf):
                main()
        self.assertIn("API calls:", buf.getvalue())

    def test_csv_output(self) -> None:
        path = self._make_file([{"type": "api_call"}])
        buf = io.StringIO()
        with patch.object(sys, "argv", ["prog", "--file", path, "--csv"]):
            with patch("sys.stdout", buf):
                main()
        self.assertIn("api_calls", buf.getvalue())

    def test_session_filter(self) -> None:
        path = self._make_file([
            {"type": "api_call", "session_id": "s1", "input_tokens": 10},
            {"type": "api_call", "session_id": "s2", "input_tokens": 99},
        ])
        buf = io.StringIO()
        with patch.object(sys, "argv", ["prog", "--file", path, "--session", "s1"]):
            with patch("sys.stdout", buf):
                main()
        out = buf.getvalue()
        self.assertIn("API calls:", out)

    def test_compare_table(self) -> None:
        path = self._make_file([
            {"type": "api_call", "session_id": "a", "input_tokens": 10},
            {"type": "api_call", "session_id": "b", "input_tokens": 20},
        ])
        buf = io.StringIO()
        with patch.object(sys, "argv", ["prog", "--file", path, "--compare", "a", "b"]):
            with patch("sys.stdout", buf):
                main()
        out = buf.getvalue()
        self.assertIn("Delta", out)

    def test_compare_csv(self) -> None:
        path = self._make_file([
            {"type": "api_call", "session_id": "a"},
            {"type": "api_call", "session_id": "b"},
        ])
        buf = io.StringIO()
        with patch.object(sys, "argv", ["prog", "--file", path, "--compare", "a", "b", "--csv"]):
            with patch("sys.stdout", buf):
                main()
        out = buf.getvalue()
        self.assertIn("api_calls", out)


if __name__ == "__main__":
    unittest.main()
