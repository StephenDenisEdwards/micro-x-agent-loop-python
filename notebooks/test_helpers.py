"""Shared setup for integration test notebooks.

Provides path configuration, pricing bootstrap, factories, and assertion
helpers so notebook cells stay focused on the tests themselves.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup — add src/ and tests/ to sys.path
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_TESTS = _ROOT / "tests"

for p in (_SRC, _ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

# ---------------------------------------------------------------------------
# Re-exports from the project (available after path setup)
# ---------------------------------------------------------------------------

from micro_x_agent_loop.usage import UsageResult, PRICING, load_pricing_overrides, _lookup_pricing, estimate_cost  # noqa: E402
from micro_x_agent_loop.metrics import SessionAccumulator, build_api_call_metric  # noqa: E402
from micro_x_agent_loop.tool_search import should_activate_tool_search  # noqa: E402
from micro_x_agent_loop.turn_classifier import classify_turn, TurnClassification  # noqa: E402
from micro_x_agent_loop.system_prompt import get_system_prompt  # noqa: E402
from micro_x_agent_loop.compaction import (  # noqa: E402
    NoneCompactionStrategy,
    SummarizeCompactionStrategy,
    estimate_tokens,
)
from micro_x_agent_loop.turn_engine import TurnEngine  # noqa: E402
from micro_x_agent_loop.agent_channel import BufferedChannel  # noqa: E402

from tests.fakes import FakeStreamProvider, FakeTool, FakeProvider  # noqa: E402

# ---------------------------------------------------------------------------
# Pricing bootstrap
# ---------------------------------------------------------------------------


def bootstrap_pricing() -> None:
    """Load pricing from config-base.json into the global PRICING dict."""
    config_path = _ROOT / "config-base.json"
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    PRICING.clear()
    load_pricing_overrides(config["Pricing"])


# ---------------------------------------------------------------------------
# TurnEngine factory (mirrors tests/test_turn_engine.py _make_engine)
# ---------------------------------------------------------------------------


def make_turn_engine(
    provider: FakeStreamProvider,
    events: Any,
    tools: list[FakeTool] | None = None,
    max_tool_result_chars: int = 40_000,
) -> TurnEngine:
    """Build a TurnEngine wired to fakes — same pattern as the unit tests."""
    tool_list = tools or []
    return TurnEngine(
        provider=provider,
        model="m",
        max_tokens=1024,
        temperature=0.5,
        system_prompt="sys",
        converted_tools=[],
        tool_map={t.name: t for t in tool_list},
        max_tool_result_chars=max_tool_result_chars,
        max_tokens_retries=3,
        events=events,
    )


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------

_pass_count = 0
_fail_count = 0


def assert_pass(condition: bool, label: str) -> None:
    """Print PASS/FAIL with *label* and raise on failure."""
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        print(f"  PASS: {label}")
    else:
        _fail_count += 1
        print(f"  FAIL: {label}")
        raise AssertionError(f"FAIL: {label}")


def print_summary() -> None:
    """Print overall pass/fail counts."""
    total = _pass_count + _fail_count
    print(f"\n{'='*50}")
    print(f"Results: {_pass_count}/{total} passed, {_fail_count} failed")
    if _fail_count == 0:
        print("All tests passed!")
    print(f"{'='*50}")


# ---------------------------------------------------------------------------
# Async helper — handles Jupyter's existing event loop
# ---------------------------------------------------------------------------


def run_async(coro: Any) -> Any:
    """Run an async coroutine, handling Jupyter's running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside Jupyter — use nest_asyncio
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(coro)
    else:
        return asyncio.run(coro)
