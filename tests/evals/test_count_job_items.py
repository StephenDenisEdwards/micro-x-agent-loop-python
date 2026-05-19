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

from tests.evals.harness import assert_answer_matches, assert_cost_under, run_eval

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


def _trajectory(result: object) -> str:
    """Human-readable tool trace for the failure message — this is the
    artefact we discuss after each run to decide the next config move."""
    lines = []
    for rec in result.channel.tool_records:  # type: ignore[attr-defined]
        rc = rec.get("result_chars")
        lines.append(
            f"  {rec['tool_name']}  "
            f"input={rec.get('tool_input')!r}  "
            f"result_chars={rc}"
        )
    return "\n".join(lines) or "  (no tools called)"


@pytest.mark.eval
def test_count_job_items_deterministically_without_loading_file() -> None:
    assert _TRUE_COUNT == 50, (
        f"fixture drift: expected 50 <item> elements, fixture has {_TRUE_COUNT}"
    )

    result = run_eval(
        f"count the number of job items in the file {_FIXTURE}",
        config_path=_CONFIG,
        extra_allowed_dirs=[str(_FIXTURE.parent)],
    )

    # Reproducibility guard — the config must resolve to the baseline model.
    assert result.model == _EXPECTED_BASELINE_MODEL, (
        f"{_CONFIG} resolved to model {result.model!r}, expected "
        f"{_EXPECTED_BASELINE_MODEL!r} — baseline drifted (check config-base "
        f"top-level Model / #Model inheritance)"
    )

    traj = _trajectory(result)

    # Criterion 1 — deterministic, correct answer.
    assert_answer_matches(result, rf"\b{_TRUE_COUNT}\b")

    # Criterion 2 — the whole file never entered the LLM context. This also
    # *implies* determinism here: the only way to reach 50 without the body
    # in context is to have used a counting tool.
    sizes = [
        (rec["tool_name"], rec["result_chars"])
        for rec in result.channel.tool_records
        if rec.get("result_chars") is not None
    ]
    too_big = [(n, c) for n, c in sizes if c >= _MAX_RESULT_CHARS]
    assert not too_big, (
        f"a tool dumped file content into context "
        f"(>= {_MAX_RESULT_CHARS} chars): {too_big}\n"
        f"trajectory:\n{traj}"
    )

    # Backstop — eyeballing 285 KB burns tokens; a counting path is cheap.
    assert_cost_under(result, 0.05)
