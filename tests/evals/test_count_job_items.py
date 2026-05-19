"""Scenario 1: count job items in an RSS file — the right tools, the right way.

This is a *configuration* eval, not a code regression guard. The agent code
and model are constants; the configuration (`config-anthropic-eval-NNNN.json`)
is the independent variable. The eval is the fitness function: for a given
config, does the agent select and invoke tools such that it answers

    "count the number of job items in the file jobserve-sample.rss"

1. deterministically — the count comes from a tool that counts, not from the
   LLM estimating it; and
2. without loading the whole file into the LLM context.

Both criteria collapse into one tool-agnostic signal. The fixture is ~285 KB
on a single line with exactly 50 ``<item>`` elements. If the agent eyeballs
it, the whole body (~291 K chars) enters context as one tool result. A
counting tool (ripgrep ``--count-matches`` / ``bash`` occurrence count)
returns a handful of chars. So: *if no tool result larger than a small
threshold ever entered context, the count cannot have been eyeballed — it
must have come from a counting tool, hence deterministic.*

The eval does NOT mandate a specific tool. Which counting tool, and whether
the available toolset is even sufficient, is exactly what we inspect after
each run and tune the config (or add tools) for the next numbered config.

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
_TRUE_COUNT = len(re.findall(r"<item>", _FIXTURE.read_text(encoding="utf-8")))

# Any single tool result this large or larger means file content entered the
# LLM context (fixture is ~291 K chars; a counting tool returns < ~100).
_MAX_RESULT_CHARS = 4_000


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
def test_count_job_items_deterministically_without_loading_file() -> None:
    assert _TRUE_COUNT == 50, (
        f"fixture drift: expected 50 <item> elements, fixture has {_TRUE_COUNT}"
    )

    prompt = f"count the number of job items in the file {_FIXTURE}"
    result = run_eval(
        prompt,
        config_path=_CONFIG,
        extra_allowed_dirs=[str(_FIXTURE.parent)],
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

    # Criterion 1 — deterministic, correct answer.
    assert_answer_matches(result, rf"\b{_TRUE_COUNT}\b")

    # Criterion 2 — the whole file never entered the LLM context. This also
    # *implies* determinism here: the only way to reach 50 without the body
    # in context is to have used a counting tool.
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
