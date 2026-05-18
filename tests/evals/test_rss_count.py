"""Regression eval for the ISSUE-007 residual tail.

Bug: under the `factual_lookup` routing policy the agent is sent to Haiku
with `tool_search_only` active; the startup tool_search loads fetch-style
tools but NOT `filesystem__bash`, so the "count via bash" directive is
unactionable. The agent falls back to inline `web_fetch` / eyeballing and
gets the count wrong.

This eval feeds a frozen 50-item RSS fixture (single long line — the
`grep -c` / `filesystem__grep` line-oriented trap) and asserts the agent
shells out to `bash` for an exact count. It must FAIL before the fix
(drop `tool_search_only` from `factual_lookup`) and PASS after.

Skipped unless MICRO_X_RUN_EVALS=1 (see conftest.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.evals.harness import (
    assert_answer_matches,
    assert_cost_under,
    run_eval,
)

# Eval against the config the user actually runs in the TUI
# (config-optimal-anthropic.json, which sets factual_lookup →
# Haiku + tool_search_only + pin_continuation), NOT config-base.json.
# Testing the wrong config is itself the ISSUE-007 failure mode.
_RUNTIME_CONFIG = "config-optimal-anthropic.json"

_FIXTURE = Path(__file__).parent / "fixtures" / "jobserve-sample.rss"
# Ground truth computed from the frozen fixture, so the assertion stays
# correct if the fixture is ever deliberately re-captured.
_TRUE_COUNT = len(re.findall(r"<item>", _FIXTURE.read_text(encoding="utf-8")))


@pytest.mark.eval
def test_rss_item_count_is_correct_and_cheap() -> None:
    """The real goal: the agent returns the EXACT count, cheaply, without
    eyeballing it. It must NOT mandate a specific tool — the earlier
    'must use bash, not grep' assertion was premised on the now-disproven
    belief that filesystem__grep count mode returns 1 on single-line files
    (it uses ripgrep --count-matches and returns 50 correctly). See
    ISSUE-007 §"Correction (2026-05-18)". Either filesystem__grep
    output_mode=count OR a bash occurrence count is acceptable; eyeballing
    is not.
    """
    assert _TRUE_COUNT == 50, f"fixture drift: expected 50 items, fixture has {_TRUE_COUNT}"

    result = run_eval(
        f"How many `<item>` elements are in the file {_FIXTURE}? "
        f"Give me the exact number.",
        model="claude-haiku-4-5-20251001",
        config_path=_RUNTIME_CONFIG,
        extra_allowed_dirs=[str(_FIXTURE.parent)],
    )

    # 1. Correct answer (the actual objective).
    assert_answer_matches(result, rf"\b{_TRUE_COUNT}\b")

    # 2. It used *a* counting tool rather than eyeballing — the genuine
    #    failure mode. Tool choice (grep count vs bash) is free.
    used = result.started_tools()
    assert any(
        t in used for t in ("filesystem__grep", "filesystem__bash")
    ), f"expected a counting tool (grep/bash), got: {used}"

    # 3. Cheap. The pathological path burns failed calls + retries.
    assert_cost_under(result, 0.05)
