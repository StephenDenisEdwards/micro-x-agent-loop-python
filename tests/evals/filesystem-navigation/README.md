# Filesystem-navigation eval set

Phase 5 of [PLAN-filesystem-navigation](../../../documentation/docs/planning/PLAN-filesystem-navigation.md). Verifies that the FS-navigation directive added to `system_prompt.py` (Phase 1) actually shifts model behaviour: the model should reach for dedicated FS tools rather than `bash`, and should spawn the `explore` sub-agent for vague codebase questions instead of running 6 inline greps.

The eval set is the artifact that backs **acceptance criteria #1 and #2** of the plan.

## Files

| File | Purpose |
|------|---------|
| `prompts.json` | The prompt set (eight prompts, three categories) plus per-prompt expectations and the `ignore_tools` list |
| `run.py` | The runner: invokes the agent for each prompt, parses `metrics.jsonl` for `tool_execution` events, scores against expectations |
| `README.md` | This document |

## How it works

For each prompt:

1. The runner invokes `python -m micro_x_agent_loop --run "<prompt>" --session <unique-id>`.
2. The agent runs autonomously to completion, writing tool-execution telemetry to `metrics.jsonl`.
3. The runner reads the new lines appended since the invocation started, filters by `session_id`, and extracts the set of `tool_name` values from `type=tool_execution` records.
4. The runner compares the observed tool set against the prompt's `expect` block.
5. Pass/fail is reported per prompt; a final summary checks the 80% threshold.

`spawn_subagent` is checked separately because it's a pseudo-tool (handled inline in `turn_engine.py`), not an MCP call.

`tool_search`, `ask_user`, and the four `task_*` pseudo-tools are in the `scoring.ignore_tools` list — they're discovery and orchestration plumbing, not the FS-tool selection the directive is about.

## Prompt categories

| Category | Count | Expected behaviour |
|----------|-------|--------------------|
| `narrow` | 3 | Single dedicated tool (read_file / glob / grep). **Must NOT spawn explore** — the work is too small to justify the overhead. **Must NOT use bash.** |
| `broad` | 3 | grep + read_file (and possibly in parallel — see Limitations). **Must NOT use bash** for FS work. Spawning explore is allowed but not required. |
| `vague` | 2 | Open-ended codebase exploration. **Must spawn explore** so search noise stays in the sub-agent's context. **Must NOT use bash.** |

Each prompt's `rationale` field explains the design intent.

## Running the eval

Required: a working agent install, MCP servers configured, and a `metrics.jsonl` path.

```sh
python tests/evals/filesystem-navigation/run.py \
    --metrics-path /path/to/metrics.jsonl
```

The path matches whatever `JsonlSinks` entry in your `config-base.json` (or override) points the agent at. The runner appends — it does not overwrite — and only reads lines written during the run.

### Optional flags

| Flag | Purpose |
|------|---------|
| `--config PATH` | Pass a specific config to the agent (useful for using a cheaper model for evals) |
| `--retries N` | Per-prompt retry budget. A prompt only fails if it loses on every attempt. Use this to absorb model non-determinism |
| `--only ID[,ID]` | Run only the named prompts |
| `--output PATH` | Write structured results to a JSON file alongside the human-readable output |

### Example: cheap-model eval, 2 retries, JSON output

```sh
python tests/evals/filesystem-navigation/run.py \
    --metrics-path /path/to/metrics.jsonl \
    --config configs/eval-haiku.json \
    --retries 2 \
    --output eval-results-2026-05-09.json
```

## Pass criterion

- **Threshold: 80%.** Matches the plan's acceptance criterion. The runner's exit code is 0 if the threshold is met, 1 otherwise.
- **Non-determinism handling: per-prompt retries.** A prompt counts as failing only if every attempt fails. Set `--retries 2` for a 3-attempt budget.

## Cost note

Every invocation makes at least one LLM call (often more, since the agent may take multiple turns to complete a prompt). Eight prompts × three attempts each ≈ 24 invocations. Run against a cheap model (Haiku via the Anthropic provider, or Ollama) for routine eval runs; use the production model only when verifying behaviour for a production-config change.

## Limitations

### Parallelism is not scored programmatically

The directive recommends issuing independent FS calls in one assistant response so they run concurrently via `asyncio.gather` (`turn_engine.py:459`). Verifying this from `metrics.jsonl` alone requires correlating timestamps and turn numbers, which is fragile. For now, parallelism is a manual-inspection item:

- Run the eval with `--output results.json`.
- Open `metrics.jsonl` for one of the broad prompts.
- Look at consecutive `tool_execution` records: if their `turn_number` matches and their `timestamp` deltas are small, they ran in parallel.

### The eval is read-only

All eight prompts are read-only against the agent's own codebase. They do not exercise `edit_file`, `write_file`, `append_file`, or `delete_file` — adding edit-prompts would require a fixture directory the agent could safely mutate. Edit-tool behaviour is verified by manual interactive use of the agent (which is also what surfaced the bugs that informed the Phase 2 spec).

### Single-model verification by default

The eval uses whichever provider/model your config points at. Cross-model verification (the directive should work on Haiku, Sonnet, Opus, GPT-4o, etc.) requires running the eval against each model separately. The runner doesn't yet sweep models for you — pass `--config` per-model and aggregate manually.

### `bash`-as-test-runner is not exercised

A real `bash` invocation for legitimate purposes (running tests, building, package management) would surface false positives in the directive. None of the eval prompts trigger that path. If the directive ever discourages bash for legitimate test runs, that's a regression worth a separate eval prompt.

## Tuning loop

If the eval shows the model still inlines greps for vague questions or reaches for `bash` for FS work:

1. Tighten the relevant section of `_FS_NAVIGATION_DIRECTIVE` in `src/micro_x_agent_loop/system_prompt.py`.
2. Tighten the affected tool's description in `mcp_servers/ts/packages/filesystem/src/tools/<tool>.ts` (the descriptions are the model's primary signal — directives reinforce, descriptions decide).
3. Re-run the eval.
4. If the vague-prompts category specifically is failing, check the `explore` sub-agent's description and the `_SUBAGENT_DIRECTIVE` in `system_prompt.py`.

Each tuning round is fast (~minutes) and the eval gives a fast yes/no answer.
