# Plan: Behavioural eval suite

**Status: Planned (2026-05-15).** Not started. This is the implementation plan for the highest-leverage mitigation of [ISSUE-007: Prose-contract drift across policy layers](../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md).

## Context

Read [ISSUE-007](../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) first — it is the design rationale. This document is the implementation plan only.

**Naming note (resolve a collision before it confuses anyone):** "Option B" was used two ways in the originating discussion. In the *fix-the-web_fetch-bug* exchange, Option A = "patch the layer, ship, pray" and **Option B = "write the eval first, watch it fail, then patch"**. In ISSUE-007's formal *Options considered*, **Option A = the eval suite** and Option B/C/D are source-of-truth / canonical-recipe / codegen. They refer to the same underlying deliverable: a behavioural eval suite that gates fixes. This plan builds that suite and operationalises the eval-first workflow. Where the two numbering schemes disagree, this plan wins; the issue's "Recommendation" section's priority order (eval suite first) is the canonical sequencing.

The agent's behaviour on a prompt is the emergent result of ~10 policy layers (MCP server defaults, wrapper defaults, tool descriptions, `ToolResultOverrides`, `system_prompt.py`, `RoutingPolicies`, `tool_search_only`, path-guard, process/`dist` state, conversation cache) that are never statically checked against each other. The only signal that two layers disagree is observing the agent fail on a real prompt. Today that signal is "a human notices in the TUI"; this plan makes it "a test turns red".

**Harness decision (made 2026-05-15, after a reversal — recorded so the reasoning isn't lost): DIY pytest + `BufferedChannel` first; Inspect AI as a later escalation.** This was briefly flipped to "Inspect AI from the start" on a learning/CV rationale, then reverted. The reversal logic: the CV value of this work lives in the *capability* ("designed an automated harness that gates LLM-agent behaviour regressions"), not in the *tool name* — no UK-contract-market spec names Inspect AI, and keyword-matching a CV to a niche framework is a weak strategy regardless. Since the CV argument was the *only* thing that justified the slower Inspect-first path, removing it returns the decision to its engineering merits: DIY-first is free, uses infrastructure that already exists (`BufferedChannel` already records every tool event), and closes the open ISSUE-007 tail soonest. Inspect AI remains a deliberately-chosen later learning exercise (Phase 5) — better undertaken once the suite exists and the assertion shapes are known, which is the right time to learn a framework anyway. The framework survey and the full reversal rationale live in ISSUE-007 §"Tooling for Option A" → "Decision for this project".

## Goal

After this plan lands:

- A `tests/evals/` suite runs a real (or replayed) agent against canonical prompts and asserts on **tool-call sequence + final answer + cost ceiling**.
- The residual open tail of ISSUE-007 (Haiku + `tool_search_only` never loads `filesystem__bash` for `factual_lookup`, so the count-via-bash directive is unactionable) has a regression eval that **fails before** the fix and **passes after**.
- Every future change to a directive, MCP server, tool description, or routing policy can be validated green/red before shipping, instead of discovered in production.
- Running the suite costs ≈$0 on unchanged prompt/model/tool combinations (response replay), and a few dollars on a full live re-record.

Non-goals: replacing the LLM, measuring model quality, RAG metrics. We test the *integration of our layers*, with the model pinned.

## Phase 0 — Harness scaffold

- `tests/evals/__init__.py`, `tests/evals/conftest.py`.
- `build_agent_for_eval(*, model: str, config_path: str = "config-base.json", channel: BufferedChannel) -> Agent` — constructs the agent the same way the TUI does (same `bootstrap`, same config), with the model **pinned** (never `#Model` indirection — evals must not drift when the default model moves).
- `tests/evals/fixtures/` for frozen inputs (captured once, committed, never live).
- Assertion helpers: `assert_tool_sequence(channel, expected, *, allow_extra=True)`, `assert_answer_matches(channel, regex)`, `assert_cost_under(channel, usd)`. These read `channel.tool_events` (incl. the `tool_input`, `result_chars`, `was_summarized`, `was_truncated`, `duration_ms` fields), `channel.text`, and `channel.turn_usages`.
- Tolerances baked into helpers: regex (not exact) match on commands; `allow_extra` for 1–2 bonus tool calls; cost ±30%.
- Marked `@pytest.mark.eval` so the default `pytest tests/` run can exclude them (they cost money / need network unless replaying).

## Phase 1 — First regression eval = the ISSUE-007 residual tail

This phase is the proof the whole approach works, and it closes the open issue.

1. Capture `tests/evals/fixtures/jobserve-sample.rss` — a one-shot freeze of the live JobServe RSS (50 `<item>` elements). Never re-fetched by the test.
2. Write `tests/evals/test_rss_count.py`:
   - Prompt: *"How many `<item>` tags are in tests/evals/fixtures/jobserve-sample.rss?"*
   - Model pinned to `claude-haiku-4-5-20251001` (the model that actually fails today).
   - Assert `filesystem__bash` in the started-tool sequence; assert `filesystem__grep` **not** used (line-oriented trap); assert answer matches `\b50\b`; assert cost < $0.05.
3. **Run it. Watch it fail.** The failure message must name the bug ("expected `filesystem__bash`, got `['web__web_fetch']`"). This proves the eval has signal.
4. Apply the deferred fix from ISSUE-007 §"Current state": drop `tool_search_only` from the `factual_lookup` `RoutingPolicies` entry in `config-base.json` (or add a mandatory second `tool_search` query before counting — spike both, pick by eval pass + cost delta).
5. **Run it again. Watch it pass.**
6. Commit fixture + test + config change as **one** changeset. The diff is the record of both the fix and its regression guard.

Acceptance for this phase: the ISSUE-007 residual tail is closed *and* permanently guarded. Update ISSUE-007 §"Current state" to mark the tail resolved with a pointer to the eval.

## Phase 2 — Broaden to the canonical prompt set

Port the rest of this session's failure modes into evals (each is already a known good/bad case):

| Eval | Prompt shape | Key assertions |
|------|--------------|----------------|
| `test_rss_count` | count single-line RSS | bash (not grep), answer=50, cost ceiling *(Phase 1)* |
| `test_fetch_then_count_multiturn` | turn 1 fetch+title, turn 2 "how many?" | turn 2 shells out (not eyeball-from-context), correct count |
| `test_save_to_file_roundtrip` | fetch with `save_to_file=./.fetch/x`, then size+count | `web_fetch` result_chars=0; relative path accepted; file read back |
| `test_read_and_reason` | fetch Wikipedia article, summarise a section | plain inline `web_fetch`; **no** `[OUTPUT TRUNCATED]`; no `save_to_file` |
| `test_large_fetch_no_truncation` | fetch ~170 KB page, enumerate headings | result_chars ≈ full size; `was_truncated=False` |

Each is ~30–40 lines. Five evals = a usable safety net.

## Phase 3 — Cost & replay

- Integrate [VCR.py](https://github.com/kevin1024/vcrpy) (or equivalent) so LLM/MCP HTTP traffic is recorded once and replayed. Cassettes committed under `tests/evals/cassettes/`, keyed by prompt + model + tool-set hash.
- `pytest -m eval` replays by default (≈$0, no network). `pytest -m eval --record` re-records (live, costs ~$2–3 for the full suite).
- Document the re-record trigger: cassettes are invalidated deliberately when the prompt/model/tools change; a stale-cassette check warns rather than silently passing.
- CI posture: on-demand (a labelled workflow / manual dispatch) initially, not per-commit, to avoid cost and flakiness on every PR. Revisit once the suite is stable.

## Phase 4 — Optional: port to Inspect AI (deliberate learning exercise)

Once Phases 0–3 exist, port the suite to [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) (UK AISI's framework) as a planned learning exercise — not because DIY has failed, but because by this point the assertion shapes are known, which is the right time to learn a framework. Expected gains: the Inspect log viewer (`inspect view`) for browsing failed-run transcripts, built-in output caching (replaces VCR.py), and dataset/scorer composition.

The integration crux: Inspect's `Solver` model assumes *Inspect* drives the model loop, but this agent owns its own loop (`TurnEngine` + `AgentChannel` + routing). The port is a custom `@solver` that constructs the real `Agent` (as Phase 0's `build_agent_for_eval` already does), runs it to completion, and writes the recorded tool-event trace / final text / usage into `TaskState` for custom scorers to read. Budget real time for this adapter — it is the bulk of the Inspect learning curve. The DIY pytest suite remains the source of truth until the Inspect port reaches parity (every Phase 2 eval green under Inspect).

Trigger to actually do this phase: Phases 0–3 complete and stable, and there is appetite for the framework-learning investment. Until then the DIY suite is sufficient and is what gates changes.

## Risks / mitigations

- **Non-determinism** → regex not exact-match; `allow_extra` tool calls; cost ±30%. If a test is flaky across 3 live runs, the assertion is too tight, not the agent wrong.
- **Eval cost creep** → replay-by-default; live only on explicit `--record`; on-demand CI, not per-commit.
- **Cassette rot** → stale-cassette check; cassettes keyed by inputs so a prompt/model/tool change forces a visible re-record rather than a silent wrong pass.
- **The eval is itself a prose contract** (ISSUE-007's own warning) → keep assertions behavioural (tool sequence, answer, cost), not implementation-detail; review eval changes as carefully as prod changes.
- **Model pinning drift** → evals pin an explicit model id; a default-model bump is a separate, deliberate eval update, never implicit.
- **Phase 4 adapter friction** (deferred risk) → does not block the working DIY suite; the Inspect port is gated on DIY parity, so a hard adapter problem degrades to "no Inspect", not "no evals".

## Acceptance criteria

1. `tests/evals/` exists with the Phase 0 harness and helpers.
2. The ISSUE-007 residual tail has a regression eval that demonstrably failed pre-fix and passes post-fix; ISSUE-007 §"Current state" updated to resolved-with-pointer.
3. ≥5 canonical evals (Phase 2 table) pass.
4. Replay mode runs the suite with no network and ~$0; `--record` documented.
5. A deliberately introduced "directive says X, tool rejects X" mismatch produces a red eval, not a runtime-only failure (demonstrated once, e.g. by reverting the `save_to_file` relative-path fix on a branch).

Partial credit is explicitly fine: Phases 0–1 alone (harness + the one regression eval) already change the iteration dynamic and close the open ISSUE-007 tail behind a guard. Phase 4 (Inspect AI) is explicitly optional and never blocks the others.

## Related

- [ISSUE-007 — Prose-contract drift across policy layers](../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md). Parent issue; this plan is its Option A / "eval-first" deliverable. The residual triggering-bug tail there is this plan's Phase 1.
- [ADR-024 — Single-Layer Tool-Result Truncation Policy](../architecture/decisions/ADR-024-single-layer-tool-result-truncation.md). One slice of the source-of-truth idea (ISSUE-007 Option B); the `test_large_fetch_no_truncation` eval guards it.
- `src/micro_x_agent_loop/agent_channel.py` — `BufferedChannel` records `tool_events` / `text` / `turn_usages`; the eval harness asserts against these.
- `config-base.json` — `RoutingPolicies` (Phase 1 fix target), `ToolResultOverrides` (eval target).
