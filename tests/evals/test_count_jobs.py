"""Scenario 2: count *jobs* in an RSS file — the honest, non-leaking prompt.

Companion to ``test_count_job_items.py``. That scenario asks for "job
*items*", which leaks the answer's shape: "items" -> ``<item>``. An agent
(or model) can shortcut straight to counting ``<item>`` without ever
understanding the file.

This scenario asks for "the number of **jobs**" — no leak. To answer it the
agent must actually:

1. recognise the file is a feed;
2. determine *what a job is in this file* — RSS 2.0 -> a job is a
   ``<channel>/<item>`` (it would be ``<entry>`` in Atom, or a namespaced
   element in some feeds); and only then
3. count that element deterministically, without loading the file into the
   LLM context.

Step 2 — schema discovery before counting — is the real capability under
test. The behavioural gates are deliberately the *same* as Scenario 1
(correct count + nothing large entering context): if the agent reaches the
true count without the file body in context, it both identified the right
element and counted it with a tool. We do NOT assert *how* it discovered the
schema (that would be implementation-detail policing — see ISSUE-007); the
trajectory is recorded for the post-run discussion, where we decide whether
a baseline failure is a config, system-prompt, or tooling problem.

Expect this to be *harder* than Scenario 1, possibly failing even on the
permissive baseline — that is the signal, not a regression.

Skipped unless MICRO_X_RUN_EVALS=1 (see conftest.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.evals.harness import EvalResult, assert_answer_matches, run_eval

# The numbered configuration under evaluation. Bump this (and only this,
# holding prompt/fixture/assertions constant) to walk the config series.
# The config — not this test — owns the model; the harness uses whatever the
# config resolves to and reports it as result.model.
_CONFIG = "config-anthropic-eval-0001.json"
# eval-0001 is the Sonnet baseline (inherits #Model from config-base). This
# is the reproducibility guard: if the base default drifts off Sonnet, the
# baseline is no longer the baseline and this must fail loudly.
_EXPECTED_BASELINE_MODEL = "claude-sonnet-4-5-20250929"

_FIXTURE = Path(__file__).parent / "fixtures" / "jobserve-sample.rss"
# Ground truth: a job == an RSS 2.0 <item>. Computed from the frozen fixture
# so the assertion stays correct if the fixture is ever re-captured.
_TRUE_COUNT = len(re.findall(r"<item>", _FIXTURE.read_text(encoding="utf-8")))

# Any single tool result this large or larger means file content entered the
# LLM context (fixture is ~291 K chars; a counting tool returns < ~100).
_MAX_RESULT_CHARS = 4_000

# Tight per-eval cap (overrides the config-level MaxAgenticIterations general
# cap). The honest prompt is expected to thrash on a weak config; 4 leaves
# room for a legit discover->count->answer path while failing fast otherwise.
_MAX_ITERATIONS = 4


def _readout(prompt: str, result: EvalResult) -> str:
    """Per-run record we discuss after each run to decide the next config
    move. Cost is *recorded, not gated* — it is the optimization axis across
    the numbered config series, and the absolute figure is cache-warmth
    bimodal (cold pays ~30k cache-creation tokens, warm pays cache-read), so
    a hard per-run ceiling would flake rather than signal. Compare cost and
    cache_hit_ratio across configs; gate only on behaviour."""
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
def test_count_jobs_requires_schema_discovery() -> None:
    assert _TRUE_COUNT == 50, (
        f"fixture drift: expected 50 <item> elements, fixture has {_TRUE_COUNT}"
    )

    prompt = f"count the number of jobs in {_FIXTURE}"
    result = run_eval(
        prompt,
        config_path=_CONFIG,
        extra_allowed_dirs=[str(_FIXTURE.parent)],
        max_iterations=_MAX_ITERATIONS,
    )

    # Reproducibility guard — the config must resolve to the baseline model.
    assert result.model == _EXPECTED_BASELINE_MODEL, (
        f"{_CONFIG} resolved to model {result.model!r}, expected "
        f"{_EXPECTED_BASELINE_MODEL!r} — baseline drifted (check config-base "
        f"top-level Model / #Model inheritance)"
    )

    readout = _readout(prompt, result)
    # Always surface the per-run record (cost is recorded data, not a gate).
    print(f"\n[eval record]\n{readout}")

    # Gate 0 — the agent converged within the cap. Hitting it means it
    # thrashed (no idea what to count / kept retrying) rather than failing
    # cleanly; that is itself the behavioural failure for this scenario.
    assert not result.turn_cap_reached, (
        f"agent hit the {_MAX_ITERATIONS}-iteration cap without converging — "
        f"thrashed on the honest prompt\n{readout}"
    )

    # Criterion 1 — correct answer. With the non-leaking prompt this also
    # implies the agent identified that a "job" == an <item> in this feed.
    assert_answer_matches(result, rf"\b{_TRUE_COUNT}\b")

    # Criterion 2 — the whole file never entered the LLM context. Together
    # with criterion 1 this means the agent discovered the right element and
    # counted it with a tool, rather than eyeballing or guessing.
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

    # Cost is NOT asserted — see _readout(). It is recorded for cross-config
    # comparison in the sweep, not a per-run pass/fail gate.
