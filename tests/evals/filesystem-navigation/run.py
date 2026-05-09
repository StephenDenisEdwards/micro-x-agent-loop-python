"""Eval runner for filesystem-navigation prompts.

Phase 5 of PLAN-filesystem-navigation. Verifies that the FS-navigation
directive in `system_prompt.py` actually shifts model behaviour: the
model should reach for dedicated tools (read_file / grep / glob /
edit_file / delete_file), spawn the explore sub-agent for vague
codebase questions, and only fall back to bash when no dedicated tool
fits.

What this script does
---------------------

For each prompt in ``prompts.json``:

1. Invoke the agent autonomously via ``python -m micro_x_agent_loop --run``
   with a unique session_id.
2. After the run, read ``metrics.jsonl`` and extract every
   ``type=tool_execution`` event scoped to that session_id.
3. Score the observed tool set against the prompt's ``expect`` block.
4. Emit a per-prompt verdict and a final summary.

Pass criterion: >= 80%% of prompts pass (matches PLAN-filesystem-navigation
acceptance criterion). For non-determinism, re-run the failing prompt up
to ``--retries`` times -- a prompt only counts as failing if it loses on
every attempt.

Usage
-----

::

    python tests/evals/filesystem-navigation/run.py \\
        --metrics-path /path/to/metrics.jsonl

Optional arguments:

  --config PATH       Pass a config file to the agent invocation.
  --retries N         Per-prompt retry budget (default: 0 -- single shot).
  --only ID[,ID]      Only run the named prompts.
  --output JSON_PATH  Write the structured results to this path.

Limitations
-----------

- Parallelism is not scored programmatically. The directive recommends
  issuing independent FS calls in one assistant response so they run
  concurrently via asyncio.gather, but verifying this from
  metrics.jsonl alone is fragile (timing-based heuristics are noisy).
  For now, parallelism is a manual-inspection item -- see the README.
- Cost: each invocation makes at least one LLM call. Default is your
  configured provider/model. Override via the agent's config to use a
  cheap model (Haiku) when running the eval frequently.
- The agent must be installed and runnable:
  ``python -m micro_x_agent_loop --run "test"`` should work in your environment.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

EVAL_DIR = Path(__file__).parent
PROMPTS_FILE = EVAL_DIR / "prompts.json"

PASS_THRESHOLD_PCT = 80.0


@dataclass
class PromptResult:
    """Per-prompt scoring result."""

    id: str
    category: str
    passed: bool
    attempts: int
    observed_tools: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    subagent_expectation: str = ""  # "must_spawn", "must_not_spawn", or ""
    subagent_observed: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "passed": self.passed,
            "attempts": self.attempts,
            "observed_tools": self.observed_tools,
            "missing": self.missing,
            "forbidden": self.forbidden,
            "subagent_expectation": self.subagent_expectation,
            "subagent_observed": self.subagent_observed,
            "notes": self.notes,
        }


def load_eval_set() -> dict:
    if not PROMPTS_FILE.exists():
        sys.exit(f"prompts file not found: {PROMPTS_FILE}")
    parsed: dict = json.loads(PROMPTS_FILE.read_text())
    return parsed


def metrics_offset(path: Path) -> int:
    """Return the current byte size of the metrics file, or 0 if missing."""
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def read_new_metrics(path: Path, start_offset: int, session_id: str) -> list[dict]:
    """Read metrics records appended since ``start_offset``, filtered by session_id."""
    if not path.exists():
        return []
    records: list[dict] = []
    with open(path, "rb") as f:
        f.seek(start_offset)
        for raw_line in f:
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("session_id") != session_id:
                continue
            records.append(record)
    return records


def extract_observed_tools(records: list[dict], ignore: set[str]) -> tuple[set[str], bool]:
    """Return (set of tool names that ran, whether spawn_subagent was called)."""
    observed: set[str] = set()
    subagent_spawned = False
    for record in records:
        if record.get("type") != "tool_execution":
            continue
        name = str(record.get("tool_name") or "")
        if not name:
            continue
        if name == "spawn_subagent":
            subagent_spawned = True
            continue
        if name in ignore:
            continue
        observed.add(name)
    return observed, subagent_spawned


def invoke_agent(prompt_text: str, session_id: str, config_path: str | None) -> tuple[int, str, str]:
    """Run the agent autonomously and return (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable,
        "-m",
        "micro_x_agent_loop",
        "--run",
        prompt_text,
        "--session",
        session_id,
    ]
    if config_path:
        cmd.extend(["--config", config_path])
    completed = subprocess.run(cmd, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr


def score_prompt(prompt: dict, observed: set[str], subagent_spawned: bool) -> PromptResult:
    expect = prompt.get("expect", {})
    must_use = set(expect.get("must_use", []))
    must_not_use = set(expect.get("must_not_use", []))
    must_spawn = bool(expect.get("must_spawn_subagent"))
    must_not_spawn = bool(expect.get("must_not_spawn_subagent"))

    missing = sorted(must_use - observed)
    forbidden = sorted(must_not_use & observed)

    subagent_expectation = ""
    if must_spawn:
        subagent_expectation = "must_spawn"
    elif must_not_spawn:
        subagent_expectation = "must_not_spawn"

    subagent_violation = False
    if must_spawn and not subagent_spawned:
        subagent_violation = True
    if must_not_spawn and subagent_spawned:
        subagent_violation = True

    passed = not missing and not forbidden and not subagent_violation

    return PromptResult(
        id=prompt["id"],
        category=prompt.get("category", ""),
        passed=passed,
        attempts=1,
        observed_tools=sorted(observed),
        missing=missing,
        forbidden=forbidden,
        subagent_expectation=subagent_expectation,
        subagent_observed=subagent_spawned,
    )


def run_one(
    prompt: dict,
    metrics_path: Path,
    config_path: str | None,
    ignore: set[str],
) -> PromptResult:
    """Run one prompt once and score it."""
    session_id = f"eval-{prompt['id']}-{uuid.uuid4().hex[:8]}"
    start = metrics_offset(metrics_path)
    t0 = time.monotonic()
    exit_code, stdout, stderr = invoke_agent(prompt["prompt"], session_id, config_path)
    duration = time.monotonic() - t0
    # Give file writes a beat to flush before we read.
    time.sleep(0.2)
    records = read_new_metrics(metrics_path, start, session_id)
    observed, subagent_spawned = extract_observed_tools(records, ignore)

    result = score_prompt(prompt, observed, subagent_spawned)
    result.notes = f"exit={exit_code} duration={duration:.1f}s metrics_records={len(records)}"
    if exit_code != 0:
        result.notes += f" stderr_tail={stderr.strip()[-200:]!r}"
    return result


def run_with_retries(
    prompt: dict,
    metrics_path: Path,
    config_path: str | None,
    ignore: set[str],
    retries: int,
) -> PromptResult:
    """Run a prompt up to ``retries`` extra times if it fails. Returns the best (last passing, or last attempt)."""
    last = run_one(prompt, metrics_path, config_path, ignore)
    if last.passed or retries <= 0:
        return last
    for attempt in range(2, retries + 2):
        next_result = run_one(prompt, metrics_path, config_path, ignore)
        next_result.attempts = attempt
        if next_result.passed:
            return next_result
        last = next_result
    return last


def format_per_prompt(result: PromptResult) -> str:
    badge = "PASS" if result.passed else "FAIL"
    head = f"  [{badge}] {result.id} ({result.category}, attempts={result.attempts})"
    detail_parts = [f"observed={result.observed_tools}"]
    if result.missing:
        detail_parts.append(f"missing={result.missing}")
    if result.forbidden:
        detail_parts.append(f"forbidden={result.forbidden}")
    if result.subagent_expectation:
        detail_parts.append(
            f"subagent {result.subagent_expectation}=yes observed={result.subagent_observed}",
        )
    if result.notes:
        detail_parts.append(result.notes)
    return head + "\n      " + " | ".join(detail_parts)


def summarise(results: list[PromptResult]) -> tuple[float, bool]:
    passed = sum(1 for r in results if r.passed)
    pct = (100.0 * passed / len(results)) if results else 0.0
    threshold_met = pct >= PASS_THRESHOLD_PCT
    return pct, threshold_met


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metrics-path", required=True, help="Path to metrics.jsonl that the agent writes to")
    parser.add_argument("--config", default=None, help="Optional --config to pass to the agent")
    parser.add_argument("--retries", type=int, default=0, help="Per-prompt retry budget (default: 0)")
    parser.add_argument("--only", default=None, help="Comma-separated prompt ids to run")
    parser.add_argument("--output", default=None, help="Write structured results to this JSON path")
    args = parser.parse_args()

    metrics_path = Path(args.metrics_path)
    if not metrics_path.parent.exists():
        sys.exit(f"metrics path parent does not exist: {metrics_path.parent}")

    eval_set = load_eval_set()
    ignore = set(eval_set.get("scoring", {}).get("ignore_tools", []))
    prompts: list[dict] = eval_set["prompts"]

    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        prompts = [p for p in prompts if p["id"] in wanted]
        if not prompts:
            sys.exit(f"no prompts matched --only={args.only}")

    print(f"Running {len(prompts)} prompts (retries={args.retries})")
    print(f"Metrics path: {metrics_path}")
    if args.config:
        print(f"Config: {args.config}")
    print()

    results: list[PromptResult] = []
    for i, prompt in enumerate(prompts, 1):
        print(f"[{i}/{len(prompts)}] {prompt['id']} -- {prompt['category']}")
        result = run_with_retries(prompt, metrics_path, args.config, ignore, args.retries)
        results.append(result)
        print(format_per_prompt(result))
        print()

    pct, threshold_met = summarise(results)
    by_cat: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = by_cat.setdefault(r.category or "uncategorised", {"pass": 0, "fail": 0})
        bucket["pass" if r.passed else "fail"] += 1

    print("=" * 60)
    print(f"Summary: {sum(1 for r in results if r.passed)}/{len(results)} passed ({pct:.1f}%)")
    print(f"Threshold ({PASS_THRESHOLD_PCT}%): {'MET' if threshold_met else 'NOT MET'}")
    for cat in sorted(by_cat):
        counts = by_cat[cat]
        print(f"  {cat}: {counts['pass']}/{counts['pass'] + counts['fail']} passed")

    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {
                    "summary": {
                        "total": len(results),
                        "passed": sum(1 for r in results if r.passed),
                        "pass_pct": pct,
                        "threshold_pct": PASS_THRESHOLD_PCT,
                        "threshold_met": threshold_met,
                        "by_category": by_cat,
                    },
                    "prompts": [r.to_dict() for r in results],
                },
                indent=2,
            ),
        )
        print(f"\nResults written to {args.output}")

    return 0 if threshold_met else 1


if __name__ == "__main__":
    sys.exit(main())
