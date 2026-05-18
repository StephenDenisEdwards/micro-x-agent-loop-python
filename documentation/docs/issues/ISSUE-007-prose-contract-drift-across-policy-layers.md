# ISSUE-007: Prose-contract drift across policy layers

## Date

2026-05-14

## Status

**Open.** No single code-level fix. This is an architectural issue and requires tooling (behavioural eval suite) and process changes, not patches to individual layers.

Tracking note (2026-05-15): the concrete triggering bug ("count items in an RSS feed") is mostly shipped; one residual tail remains open — Haiku + `tool_search_only` for `factual_lookup` never loads `filesystem__bash`, so the count-via-bash directive is unactionable. See §"Current state of the triggering bug". The fix for that tail is intentionally deferred until it can be applied behind a failing behavioural eval — see [PLAN-behavioural-eval-suite](../planning/PLAN-behavioural-eval-suite.md).

## Summary

The agent's behaviour on any given prompt is the emergent result of roughly ten separate policy layers that each publish a prose (or partly-structured) "contract" the LLM is expected to satisfy at runtime. These layers are not statically checked against each other. When two of them disagree, the agent either fails or — worse — silently picks a plausible-looking workaround and ships a wrong answer. Because the LLM is the integrator that has to satisfy all the contracts simultaneously, any single-layer fix can be correct in isolation while still leaving the system broken end-to-end.

We have observed this concretely. Across one debugging session on 2026-05-14 we made seven sequential single-layer fixes to chase the same surface-level failure ("count items in an RSS feed"). Each fix was correct for the layer it touched; each "next failure" was a different layer whose policy hadn't yet been updated to match. The session is documented in §Evidence below.

The deeper reason this kind of system thrashes during iteration is that **there is no compile-time check that the layers agree.** A normal program composes via typed function calls; the type checker rejects mismatches before runtime. An agent composes via prose contracts read by an LLM at inference time. The first time we discover two layers disagree is when the agent fails on a real prompt. We patch one layer. That patch creates a new prose contract, which may disagree with the next layer's contract. And so on. This is whack-a-mole as a steady state.

## Why this isn't a quick fix

The cause is not in any single file. The same root cause produces every variant of the failure:

- A directive can recommend a behaviour the tool's input validation will reject.
- A tool's output cap can shadow the agent's truncation override.
- A routing policy can hide a tool the system prompt refers to.
- A path the system prompt suggests can be valid for one tool's policy and invalid for another's.
- A change to any layer requires a process restart that mid-session changes do not get.

No additional directive, additional validator, or additional tool description can close this — each of those is itself another prose contract that has to be kept consistent with everything else.

The structural property that needs to change is **single-source-of-truth for cross-cutting policies, plus end-to-end behavioural tests that fail when any layer's prose drifts from another's**. Without those, every contributor (human or AI) who touches one layer creates new opportunities for invisible disagreement.

## The layers (today)

A single prompt — "count items in this RSS feed" — passes through these policy layers, each with its own surface contract:

| # | Layer | Surface | Disagreements possible with |
|---|-------|---------|-----------------------------|
| 1 | Upstream MCP server defaults | hardcoded caps, validation rules | layers 2, 4, 5 |
| 2 | Codegen wrapper / per-task `tools.ts` | per-call defaults, signature shape | layer 1, 5 |
| 3 | Tool description | natural-language hint to LLM | layers 1, 4, 5 |
| 4 | `ToolResultOverrides` (config-base.json) | truncation / summarisation policy | layer 1, 5 |
| 5 | `system_prompt.py` directives | recipes the LLM should follow | every other layer |
| 6 | `RoutingPolicies` (config-base.json) | which model + tool surface for which task type | layers 5, 7 |
| 7 | `tool_search_only` mode | runtime narrowing of tool catalogue | layers 5, 6 |
| 8 | Filesystem path-guard | which paths are accepted | layers 1, 5 |
| 9 | Process / `dist/` state | which code is actually running | every other layer |
| 10 | Conversation cache state | which system prompt the LLM has loaded | layers 5, 9 |

Each row is a place where someone publishes a contract. **No row is the canonical reference for any other row.** The LLM reads all of them and integrates.

## Evidence — debugging session 2026-05-14

A single user prompt ("how many job items in this RSS?") triggered the following sequence of fixes over ~3 hours, each of which appeared to be "the" fix when shipped:

1. **Removed 50,000-char default cap from `web_fetch` MCP server.** Symptom (truncated output) gone — but agent's `ToolResultOverrides` was still capping at 200,000. *(Layer 1 → Layer 4 misalignment.)*
2. **Set `ToolResultOverrides.web__web_fetch.MaxChars = 0`.** Symptom appeared resolved — but the running agent process held the old in-memory config. *(Layer 4 → Layer 9 misalignment.)*
3. **Replaced `cmd.exe` with Git Bash in `filesystem__bash`.** POSIX commands now worked — but the LLM used `grep -c` on a single-line RSS, which counts matching lines, not occurrences. *(Layer 5 was silent about this.)*
4. **Added a "use `grep -o … | wc -l`" recipe to the system prompt.** Symptom resolved for direct bash use — but on the follow-up turn the LLM chose `filesystem__grep` (line-oriented) instead, returning the entire 280 KB file. *(Layer 3 did not warn about line-orientation.)*
5. **Added a single-line-file warning to `filesystem__grep` description.** LLM now correctly used `bash` — but used `/tmp/` paths recommended by the directive, which the filesystem path-guard refused on Windows. *(Layer 8 → Layer 5 misalignment.)*
6. **Changed directive recommendation from `/tmp/` to `./.fetch/`.** Save path looked sensible — but `web_fetch`'s new `save_to_file` parameter (added two changes earlier in the same session) required absolute paths. *(Layer 1 → Layer 5 misalignment, introduced by an earlier "fix".)*
7. **Made `save_to_file` accept relative paths and `mkdir -p`.** Save now worked — but `bash` was not in the agent's loaded tool catalogue because `tool_search_only` had narrowed to "fetch web content" tools at the start of the turn. The model fell back to inline `web_fetch` and answered from in-memory content. *(Layer 7 → Layer 5 misalignment.)*

Net: seven sequential one-layer fixes, each correct, each surfacing the next misalignment. The user's question was never reliably answered until we accepted that the routed-tool model wasn't going to use `bash` at all.

Each fix above also has a corresponding ADR/test/doc update that is *itself* a new prose contract requiring future maintenance to keep aligned with the rest.

## Current state of the triggering bug (as of 2026-05-15)

So the concrete `web_fetch` failure thread is not lost behind the architectural framing, here is exactly what is shipped vs. still open for the prompt *"how many job items in this RSS?"*:

**Shipped (code merged + MCP servers rebuilt this session):**

- `web_fetch` MCP server: no default char cap; `maxChars` opt-in only. (`mcp_servers/ts/packages/web/src/tools/web-fetch.ts`)
- `web_fetch` MCP server: `save_to_file` parameter — accepts **relative paths** (resolved against the MCP server cwd, matching what `filesystem__grep`/`read_file` see) and **`mkdir -p`s the parent dir**. This closes fixes 6–7's mutual contradiction (directive said relative, tool required absolute; directory didn't exist).
- `web_fetch` returns metadata-only (`content: ""`, `saved_to: <path>`) when `save_to_file` is set, keeping the body out of conversation context.
- `filesystem__bash`: resolves to Git for Windows bash (or `FILESYSTEM_BASH_SHELL` override) instead of `cmd.exe`; POSIX pipes/redirection/`/tmp` emulation work. (`mcp_servers/ts/packages/filesystem/src/tools/bash.ts`)
- `filesystem__grep` description: explicit single-line-file warning steering to `bash grep -o … | wc -l`.
- `system_prompt.py`: "Fetching large content" + "Counting and enumerating" directives rewritten — operate-on vs. reason-about fetch shapes, `grep -o | wc -l` vs `grep -c`, in-memory-content anti-pattern, allowed-roots staging path (no `/tmp/`).
- `ToolResultOverrides`: `web__web_fetch`, `google__gmail_read`, `filesystem__read_file` set to `MaxChars: 0`; `playwright__*` wildcard. ([ADR-024](../architecture/decisions/ADR-024-single-layer-tool-result-truncation.md))
- TUI tool panel now surfaces args summary, result size, `trunc`/`summ` badges, and duration per tool call, so this class of failure is visible without a log dive.

**Still open (the residual tail — NOT yet fixed):**

- **Routing blindness.** Under the `factual_lookup` routing policy the prompt is sent to Haiku with `tool_search_only` active. The startup `tool_search` query (`"fetch web content"`) loads ~7 tools — `web_fetch`, `web_search`, `browser_*`, `read_file` — and does **not** load `filesystem__bash` or `filesystem__grep`. The count-via-bash directive (layer 5) is therefore unactionable: the model cannot call a tool it was never given. It falls back to inline `web_fetch` and answers from in-memory content (wrong, or right-by-luck). *(Layer 7 ↔ Layer 5 — still misaligned.)*

This residual item is the canonical example for the first behavioural eval (see [PLAN-behavioural-eval-suite](../planning/PLAN-behavioural-eval-suite.md)). The candidate one-line fix (drop `tool_search_only` from the `factual_lookup` policy in `config-base.json`, or add a second `tool_search` query before counting) is **deliberately not applied yet** — per this issue's own thesis, it should be applied *behind a failing eval*, not blind. Applying it without the eval would be fix #8 in the same anti-pattern.

### Correction (2026-05-18) — the grep premise was false

Writing characterization tests for the native filesystem port (ADR-025, F2) **disproved a load-bearing assumption above and throughout this issue.** Verified directly against the frozen 50-item single-line RSS fixture:

- `filesystem__grep` `output_mode:"count"` runs ripgrep **`--count-matches`** (occurrences), **not** `--count` (lines). On the single-line RSS it returns **50 — correct.** `rg --count` would return 1, but `filesystem__grep` never uses that flag.

So the recurring narrative — *"grep count returns 1 on single-line files, so the agent must use bash; the bug is that bash isn't loaded"* — **was factually wrong.** `filesystem__grep` count mode was always correct for this. Consequences:

- The original eval-run-#2 "failure" was **the eval's own assertion** (`assert_tool_used(filesystem__bash)` / `assert_tool_not_used(filesystem__grep)`) being wrong, *not* grep or the agent being wrong. An agent that used `filesystem__grep` count mode would have answered 50 correctly. We never actually verified a wrong *answer* — we assumed it from the wrong-tool assertion failing first.
- The `system_prompt.py` counting directive (the "single-line → use bash" steering) was corrected on 2026-05-18 to state the verified behaviour (count mode correct incl. single-line; the genuine line-oriented limit is *content* mode only).
- The Phase-1 eval (`tests/evals/test_rss_count.py`) was corrected to assert the real goal — the agent returns the correct count cheaply — instead of mandating a specific tool premised on the false belief.
- This is itself the textbook ISSUE-007 failure: a prose belief that never matched verified tool behaviour, propagated into an issue doc, a system-prompt directive, and an eval, costing days. It was caught only by a characterization test that actually ran the tool. **The remaining genuine question** (does `tool_search_only` narrowing on `factual_lookup` still mis-route / under-equip the model?) stands on its own and must be assessed by a corrected eval, not the disproven grep story.

## Why no single fix closes it

The failure mode is not in any one of the layers — it is in the relationship between them. The LLM at runtime reads all the prose contracts and tries to find a path that satisfies all of them. When it cannot find one (two contracts disagree), the model either:

1. **Errors out** at the tool that has the strictest contract — the easiest case to debug.
2. **Silently picks the weakest path** that doesn't get rejected, even if it produces a wrong answer (e.g. counting from inline content because the file-based path errored).
3. **Improvises** with a plausible-looking command that doesn't match any documented recipe — hardest to debug because it superficially "works".

In all three modes, the bug-finding signal comes from observing the agent's behaviour on a real prompt. There is no static signal, because there is nothing static to check.

## Options considered

### Option A — End-to-end behavioural test suite

A small library of "canonical prompts" runs against a real (or recorded) agent and asserts on:

- The sequence of tools called.
- The arguments passed to each tool.
- The final text answer (substring / regex match).
- The summed cost (within a tolerance).

Examples:
- *"Count `<item>` tags in this fixture RSS"* → asserts a single `filesystem__bash` call with `grep -o … | wc -l`, asserts the answer is "50", asserts cost < $0.05.
- *"Fetch this Wikipedia article and tell me the second section heading"* → asserts inline `web_fetch`, asserts no `[OUTPUT TRUNCATED]` in the result.
- *"Find the first job title in this RSS"* → asserts `save_to_file` was used, asserts `result_chars: 0` from `web_fetch`.

**Pros:** every layer-disagreement now produces a deterministic test failure. Contributors get a green/red signal on every change. Whack-a-mole becomes regression testing.
**Cons:** evals are themselves prose contracts (the test asserts what behaviour is "right"); they need maintenance. Running them costs money (real LLM calls). Recordings get stale.

### Option B — Single source of truth for cross-cutting policies

For each cross-cutting concept (file-staging path, truncation cap, allowed-roots list), have **one** authoritative declaration that the system-prompt directive, tool descriptions, and runtime path-policies are all generated from. Example: a `staging_paths.yaml` that declares:

```yaml
fetch_staging_dir: "./.fetch"
allowed_roots:
  - "."
  - "${FILESYSTEM_WORKING_DIR}"
  - "${FILESYSTEM_ALLOWED_DIRS}"
```

…and:
- The system prompt's directive paragraph is rendered from this file at startup.
- The path-guard is initialised from this file.
- `web_fetch.save_to_file` reads this file to resolve relative paths.

A single change to `staging_paths.yaml` is then guaranteed to update every layer that talks about staging paths.

**Pros:** eliminates a whole class of inter-layer drift mechanically. Reviewer can see the canonical declaration and trust it propagates.
**Cons:** ~5 cross-cutting concepts to identify and refactor. Some layers don't have an obvious code-injection point for the source-of-truth template.

### Option C — One canonical recipe per task type

The system prompt currently offers the LLM multiple valid paths for the same goal (3 ways to fetch-and-count). Each option is an integration point that can disagree with the rest of the system. **Pick one canonical recipe per task type and document only that one** — until evals prove the LLM needs more flexibility.

**Pros:** reduces surface area sharply. Less prose to keep aligned.
**Cons:** loses flexibility the LLM might need; might force suboptimal patterns for edge cases.

### Option D — Constrained generation (codegen pattern, broader)

For repeat workflows, replace LLM-orchestrated tool calls with codegen-generated TypeScript programs (the `tools/<task>/` pattern this project already uses). The recipe becomes code, not prose. Compile-time check, deterministic.

**Pros:** the most rigorous fix for repeated workflows; the project already has the infrastructure (`codegen__run_task`).
**Cons:** doesn't help free-form prompts that aren't worth codegening.

## Recommendation

Adopt all four, in priority order.

1. **Option A first** — the lack of behavioural tests is what made this session a 3-hour debug instead of a 15-minute one. Without evals, every fix is a guess. With evals, fixes have signal. This is the highest-leverage change.
2. **Option B second**, scoped initially to the two concepts that have already burned us this session: file staging paths and truncation/summarisation policy. (ADR-024 is the existing record of the second concept's canonicalisation; B would add the implementation.)
3. **Option C** opportunistically when refactoring directives — if a section offers three paths, pick one.
4. **Option D** for any workflow that gets repeated more than 2-3 times.

Critically: none of A-D is a fix for the *next* surface symptom. Each is a fix for the *category of system in which surface symptoms accumulate*. Until at least Option A is in place, expect this debugging pattern to recur on every non-trivial behavioural change.

## Tooling for Option A (eval suite)

We should not roll our own framework if a good one exists. Surveyed the OSS landscape; three are worth looking at for this codebase, and one DIY path is genuinely viable as a first step.

### Top three frameworks

#### 1. Inspect AI (UK AISI; used internally at Anthropic) — most aligned

[github.com/UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai). OSS (Apache-2.0), Python, purpose-built for evaluating AI systems including tool-using agents.

The model is *task → solver → scorer*. The solver wraps the agent; the scorer reads the recorded trace and asserts. What you get:

- **Trace-level assertions** — full tool-call sequence, args, results all addressable in the scorer.
- **Multi-provider** out of the box (Anthropic, OpenAI, Ollama, Google) — matches this project's provider abstraction directly.
- **Cost and token tracking** baked into the run record; trivial to fail a test on cost-over-budget.
- **VSCode extension** for browsing recorded eval runs — genuinely useful debug surface.
- Built-in support for response caching so most CI runs don't hit the API.

Highest fit by feature alignment. The cost is one more dependency and a new test-discovery path (Inspect tests don't run under pytest by default).

#### 2. DeepEval — best pytest integration

[github.com/confident-ai/deepeval](https://github.com/confident-ai/deepeval). OSS (Apache-2.0), Python.

- **Pytest-native** — `pytest tests/evals/` Just Works, important because this project already uses pytest extensively.
- **`ToolCorrectnessMetric`** — asserts the agent called the right tools with the right args. Deterministic, no judge-LLM cost.
- **`TaskCompletionMetric`** and friends — these are LLM-as-judge, so they cost money per assertion.
- Multi-provider via configurable per-metric model.

More opinionated about its metric model than Inspect; less rich for trace-level assertions. Easier to learn if you're already comfortable with pytest.

#### 3. promptfoo — skip for this case

[github.com/promptfoo/promptfoo](https://github.com/promptfoo/promptfoo). YAML-driven, language-agnostic. Strong for prompt-vs-prompt and model-vs-model comparison; weak for agent trace assertions. The failures we're trying to catch are about *sequences of calls*, not about prompt quality. Not the right shape.

### DIY: pytest + `BufferedChannel` — start here

This project already has the infrastructure for a behavioural eval. `BufferedChannel` in `agent_channel.py` records every `emit_tool_started` / `emit_tool_completed` call to a list (`channel.tool_events`). A test that:

1. Constructs a real `Agent` with a `BufferedChannel`.
2. Submits a fixture prompt via `agent.send(...)`.
3. Asserts on `channel.tool_events` + `channel.text` + `channel.turn_usages` (cost).

…is roughly 30 lines of pytest code per prompt. Ten of those tests is a usable eval suite. No new dependency, no new test runner, lives next to the existing tests.

Sketch:

```python
def test_count_rss_items_uses_bash_not_filesystem_grep() -> None:
    channel = BufferedChannel()
    agent = build_agent(channel=channel, model="claude-haiku-4-5-20251001")
    asyncio.run(agent.send("How many <item> tags in tests/fixtures/jobserve.rss?"))

    tool_names = [e[2] for e in channel.tool_events if e[0] == "started"]
    assert "filesystem__bash" in tool_names, f"Expected bash, got {tool_names}"
    assert "filesystem__grep" not in tool_names, "Should not use line-oriented grep on RSS"

    assert re.search(r"\b50\b", channel.text), f"Expected count of 50; got: {channel.text}"

    total_cost = sum(u.get("estimated_cost_usd", 0) for u in channel.turn_usages)
    assert total_cost < 0.05, f"Cost regression: ${total_cost:.3f}"
```

For ten tests at this shape, expect:

- ~$2-3 per full suite run if every test hits a real LLM.
- ~$0.20 per run with HTTP-level response caching (e.g. VCR.py, requests-cache, or a project-local cassette store keyed by prompt + model + tools).
- Zero per run for unchanged tests if you commit the cassettes and only re-record when changing the prompt/model/tools.

### Recommended sequence

The generic recommendation below optimises for *fastest path to a working fix* and **is the operative guidance for this project** — see "Decision for this project" immediately after for the (briefly-reversed-then-reverted) reasoning.

1. **Write the first 5-10 evals as pytest + `BufferedChannel`.** Free, uses what you already have, gives you concrete assertion shapes.
2. **Once you find yourself wanting things this can't easily express** — eval-set diffing, HTML reports of failed runs, side-by-side model comparison, recording management — port to **Inspect AI**. Closest fit if you outgrow DIY.
3. **Do not pick a framework first.** Write three tests as plain pytest, *then* pick. Adopting a framework before you know what assertions you need locks in choices you'd rather defer.

### Decision for this project (2026-05-15): DIY pytest first, Inspect AI as a later exercise

This decision was made, briefly reversed, and reverted — the path matters, so it is recorded in full:

1. **Initial:** DIY pytest + `BufferedChannel` first (the generic recommendation above), Inspect AI as a later escalation.
2. **Reversed to "Inspect AI from the start"** on a learning/CV rationale: Inspect is UK AISI's framework and hands-on experience is portable and CV-relevant, so the steeper curve is a deliverable not a cost.
3. **Reverted to the initial position.** The CV rationale was the *only* thing that justified the slower Inspect-first path, and it does not hold up: the CV value of this work is the **capability** ("designed an automated harness that gates LLM-agent behaviour regressions in CI"), not the **tool name**. No UK-contract-market spec (e.g. JobServe) names Inspect AI, ATS/recruiter matching is on broad terms, and keyword-matching a CV to a niche framework is a weak strategy regardless. Remove the CV argument and the decision returns to its engineering merits, where DIY-first wins: free, uses infrastructure that already exists (`BufferedChannel` records every tool event), closes the open ISSUE-007 tail soonest.

**Net decision:** DIY pytest + `BufferedChannel` for Phases 0–3. Inspect AI is a deliberately-chosen *later* learning exercise (plan Phase 4), undertaken once the suite exists and the assertion shapes are known — which is the better time to learn a framework anyway, and loses nothing because the DIY suite already gates changes. The framework survey above stands as a reference; the "Recommended sequence" is the operative guidance for this project. Full plan: [PLAN-behavioural-eval-suite](../planning/PLAN-behavioural-eval-suite.md).

### Frameworks to skip unless there's a specific reason

- **LangSmith** — couples to LangChain SDK.
- **Phoenix / Arize / Galileo / Braintrust** — observability/SaaS-flavoured; more than this needs.
- **OpenAI Evals** — heavy and OpenAI-coupled even in nominally model-agnostic modes.
- **Ragas / TruLens** — RAG-specific; the failure modes are different.

### Things to know going in

- **Non-determinism is real.** Same prompt + same model produces slightly different tool sequences across runs. Assertions need wiggle room: regex-match the bash command rather than exact-string-match; allow 1-2 extra tool calls beyond the minimum; tolerate cost ± 30%.
- **What you're testing is the integration, not the LLM.** Pin the model in eval config (don't `Model: "#Model"` indirect to whatever the current default is). When you move the default, the evals should ride a separate model bump.
- **Recording mode is the lifesaver.** Run once, record LLM responses, replay forever. All three frameworks support this in some form; for the DIY path, [VCR.py](https://github.com/kevin1024/vcrpy) is the standard.

## What is NOT a fix (anti-pattern)

The following look like fixes but extend the failure mode:

- **More directives.** Each new directive is itself a new prose contract requiring alignment with every other layer.
- **More tool-description warnings.** Same — adds prose surface, doesn't reduce drift.
- **A "smarter" model.** Sonnet handled this session's prompts better than Haiku, but the underlying architecture failure exists for both. A more capable LLM masks the symptoms longer; it doesn't remove the cause.
- **Per-tool validation that "helpfully" rejects mistakes.** Doesn't help — by the time validation runs, the LLM has already committed to a path. The validation just produces a friendlier error message, not a different agent behaviour.

## Acceptance criteria

This issue is "Resolved" when **all** are true:

1. A behavioural test suite (Option A) exists and runs in CI or on-demand.
2. Each test asserts a tool sequence + final answer + cost ceiling.
3. At least the two highest-traffic cross-cutting policies (file staging paths, truncation/summarisation) have a single declared source-of-truth (Option B).
4. The system prompt and at least three tool descriptions are derived from those sources of truth at startup, not hand-edited prose.
5. A new bug of the form "directive says X, tool rejects X" produces a red test, not a runtime failure.

Partial credit is fine — Option A alone would change the iteration dynamic substantially.

## Related

- [PLAN-behavioural-eval-suite](../planning/PLAN-behavioural-eval-suite.md). The implementation plan for Option A (and the entry point for B/C/D). The residual triggering-bug tail (§"Current state") is its first regression eval.
- [ADR-024 — Single-Layer Tool-Result Truncation Policy](../architecture/decisions/ADR-024-single-layer-tool-result-truncation.md). Records one canonical declaration (truncation policy = `ToolResultOverrides`). Implements one slice of Option B for one concept. This issue is the broader pattern of which ADR-024 is one instance.
- [ADR-013 — Tool-result summarization reliability](../architecture/decisions/ADR-013-tool-result-summarization-reliability.md). The `ToolResultOverrides` mechanism this issue critiques the layering of.
- [ADR-014 — MCP unstructured data constraint](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md). Tool results as text — the "prose contract" surface this issue describes.
- [ISSUE-005 — `bash` tool bypasses filesystem path policy](ISSUE-005-bash-tool-bypasses-path-policy.md). A specific example of layer-disagreement (path policy varies by tool). Resolved in a way that doesn't generalise — each new tool has to remember to enforce the policy.
- `src/micro_x_agent_loop/system_prompt.py` — the largest prose-contract surface; sections on "Fetching large content" and "Counting and enumerating" were edited multiple times in the session that produced this issue.
- Session log `.micro_x/tui.log` lines 19295–19651 (sessions `7513521e`, `7ea99c47`, `0270bfae`, `79e3c189`, `96323279`) — chronicle of the seven sequential fixes summarised in §Evidence.
