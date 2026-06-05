"""Scenario 3: count jobs — structure GIVEN in the prompt.

Same fixture/config/gates as Scenario 2 (``test_count_jobs.py``), one thing
changed: the prompt tells the agent the file is an RSS 2.0 feed and a job is
an ``<item>`` element. This removes the schema-discovery step entirely.

Purpose: test the hypothesis that schema-ascertainment was the whole problem.
If the failures (``&lt;item&gt;`` escaping, whole-file reads, thrash) vanish
once structure is handed over, a structure-probe tool will fix Scenario 2.
If they persist, the problem is deeper than discovery.

Runs once like the other scenarios; run it repeatedly by hand to see a
pass *rate* (same inputs have produced 1 FAIL / 2 PASS — a single run is
not a verdict).

Skipped unless MICRO_X_RUN_EVALS=1 (see conftest.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.evals.harness import EvalResult, assert_answer_matches, run_eval

_CONFIG = "configs/evals/config-anthropic-eval-0001.json"
_EXPECTED_BASELINE_MODEL = "claude-sonnet-4-5-20250929"

_FIXTURE = Path(__file__).parent / "fixtures" / "jobserve-sample.rss"
_TRUE_COUNT = len(re.findall(r"<item>", _FIXTURE.read_text(encoding="utf-8")))

_MAX_RESULT_CHARS = 4_000
_MAX_ITERATIONS = 4


def _readout(prompt: str, result: EvalResult) -> str:
    lines = [
        f"  prompt:  {prompt}",
        f"  ANSWER:  {result.text!r}",
        f"  config={_CONFIG}  model={result.model}",
        f"  cost=${result.cost_usd:.5f}  "
        f"cache_created={result.cache_creation_tokens} "
        f"cache_read={result.cache_read_tokens} "
        f"hit_ratio={result.cache_hit_ratio():.0%}",
        f"  turn_cap_reached={result.turn_cap_reached}",
        "  tools:",
    ]
    for rec in result.channel.tool_records:
        lines.append(
            f"    {rec['tool_name']}  "
            f"input={rec.get('tool_input')!r}  "
            f"result_chars={rec.get('result_chars')}"
        )
    if not result.channel.tool_records:
        lines.append("    (no tools called)")
    return "\n".join(lines)


@pytest.mark.eval
def test_count_jobs_structure_given() -> None:
    assert _TRUE_COUNT == 50, (
        f"fixture drift: expected 50 <item> elements, fixture has {_TRUE_COUNT}"
    )

    prompt = (
        f"This file is an RSS 2.0 feed; each job is an <item> element. "
        f"Count the number of jobs in {_FIXTURE}"
    )
    result = run_eval(
        prompt,
        config_path=_CONFIG,
        extra_allowed_dirs=[str(_FIXTURE.parent)],
        max_iterations=_MAX_ITERATIONS,
    )

    assert result.model == _EXPECTED_BASELINE_MODEL, (
        f"{_CONFIG} resolved to model {result.model!r}, expected "
        f"{_EXPECTED_BASELINE_MODEL!r} — baseline drifted"
    )

    readout = _readout(prompt, result)
    print(f"\n[eval record]\n{readout}")

    assert not result.turn_cap_reached, (
        f"agent hit the {_MAX_ITERATIONS}-iteration cap without converging "
        f"even with structure given\n{readout}"
    )

    assert_answer_matches(result, rf"\b{_TRUE_COUNT}\b")

    # A result that was summarized is a violation too: summarization only
    # fires on a large result, so it means the agent pulled the file and the
    # shrink merely hid it from this check (the "fake pass").
    offenders = [
        (
            rec["tool_name"],
            rec.get("result_chars"),
            "summarized" if rec.get("was_summarized") else "oversized",
        )
        for rec in result.channel.tool_records
        if rec.get("was_summarized")
        or (rec.get("result_chars") is not None and rec["result_chars"] >= _MAX_RESULT_CHARS)
    ]
    assert not offenders, (
        f"a tool pulled file content into context (>= {_MAX_RESULT_CHARS} "
        f"chars, or summarized — summarization hides a large read): "
        f"{offenders}\n{readout}"
    )
