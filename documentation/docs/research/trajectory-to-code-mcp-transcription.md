# Trajectory-to-Code: Transcribing an Agent Run into Runnable Code Against the Same MCP Surface

**Status:** Research note
**Date:** 2026-05-18
**Author:** Stephen D Edwards (with Claude)
**Relevance:** Directly informs the `codegen-templates/` system and the `jobserve-processor` task family already registered in the codegen manifest, and the Phase 0 evals harness (`tests/evals/`).

---

## Abstract

The pattern under evaluation: an agent first performs a task interactively using its MCP toolset; the LLM then **transcribes the trajectory it just executed** into code inside a template whose MCP surface is *identical* to the one it used live. The generated artefact is expected to "produce the same or very similar results" as the agent run, but cheaply, repeatably, and inspectably.

This note evaluates the pattern, separates its real benefits from its illusory ones, identifies its core failure mode (it is **behavioural cloning of a single trajectory**), specifies the engineering contract that makes it safe, relates it to the evals harness already in this repo, and surveys the relevant literature.

**Bottom line:** the idea is sound and worth building — the cost/latency win alone justifies it — but it is behavioural cloning and must be treated as such: a cheap, fast clone that is only safe behind a live *drift canary* and *loud* assertion failures, with provenance linking the artefact back to its generating run. The agent run and the generated artefact are not "two phases of one workflow" so much as **two phases with a cache-invalidation contract between them**.

---

## 1. The pattern

Two framings must be distinguished, because they have very different risk profiles:

1. **Design-from-scratch (weak framing).** The LLM is asked to "write a script that achieves the same goal," typically against native SDKs (`googleapiclient`, `requests`, `pypdf`). This re-implements the workflow and reintroduces a shape-translation gap (does `users().messages().get(format="full")` return what `gmail_read` returned? — not exactly).
2. **Trajectory transcription against matched MCPs (strong framing).** The template exposes the *same MCP servers* the agent used. Every `mcp__google__gmail_search` in the trajectory has a 1:1 counterpart in the generated code, with the same parameters and the same observed response shape. The LLM is not designing; it is **recording the workflow it just executed**, with the concrete tool-result snippets from the run in its context.

This note evaluates framing (2). Framing (1) is strictly weaker and is not the proposal.

### What framing (2) genuinely resolves

- **Fidelity gap closes.** Because the MCP response shapes in the generated code are exactly what the LLM already parsed in context, the parsing code mirrors what it already did. No SDK shape-translation reasoning.
- **Anticipation → recording.** Edge cases that *occurred* in the run (a `web_fetch` provenance error → Chrome-MCP pivot; expired jobs → email-blurb fallback; two same-date emails → merge) are encoded with the code path that actually worked, not a hypothetical guess.

These are real and the design should lean on them. They are **not** the contested part.

---

## 2. The core failure mode: behavioural cloning of one trajectory

A trajectory is **one sample from the agent's policy, not the policy.** Transcribing it yields a program that handles *the union of conditions that occurred in exactly one episode*, then runs on future inputs drawn from a distribution it never observed.

The "recording, not anticipating" reframing closes the gap *for the demonstrated trajectory* and reopens it *for every future one*:

- The `web_fetch` → Chrome-MCP branch exists only because that failure happened that day. A *different* failure next week has no branch and no judgement available to grow one.
- "Split the email body on dashed separators ≥ 20" became a hard-coded regex. The agent *inferred* that predicate by looking at the data. The code cannot re-infer it; it asserts it. The day Jobserve changes its email template, the regex is wrong **and the code does not know it is wrong**.
- The expired-job fallback is a branch because two specific jobs expired. Three unseen failure modes are three crashes — or, worse, three confidently-wrong outputs.

This is the classic imitation-learning pathology: **compounding error under distribution shift** (Ross & Bagnell, DAgger). The agent is expensive and *self-correcting*; the cloned program is cheap and *confidently wrong* off-trajectory. The failure mode shifts from "expensive but self-correcting" to "cheap but silently wrong" — the most dangerous quadrant for any pipeline with consequences.

The right mental model is therefore **not "the LLM is a compiler from intent to workflow."** It is a **memoisation of the policy's behaviour over one input sample, with no automatic invalidation.** As with any cache, the engineering difficulty is not producing it — it is knowing when it has gone stale.

---

## 3. Honest benefit accounting

| Claimed benefit | Verdict | Notes |
|---|---|---|
| **Cost / latency** | **Real and large** | 1 LLM call per judgement step vs. one agent turn per tool call; seconds vs. minutes; schedulable. This alone justifies the pattern. |
| **Auditability** | **Real but double-edged** | A 50-line function is defensible, but the judgement (regex thresholds, merge rule, ranking prompt) is now *invisible* — the transcript at least showed the reasoning. Mitigation: artefact must carry a **provenance pointer** to the generating run. Archive code + originating trajectory together. |
| **Reproducibility / determinism** | **Mostly illusory** | Orchestration is deterministic only *given identical inputs*; the inputs are a live mutable world (Gmail, a website), and the one step you actually want reproducible (the rank) is still a stochastic LLM call. You get reproducible *plumbing* — never the expensive or risky part. Do **not** headline determinism. |
| **Robustness** | **Negative vs. the agent** | The agent re-derives decisions and self-corrects. The clone does neither. The pattern *trades robustness for cost*; it does not add it. |

The case for the pattern is **cost and latency**, full stop. Everything else is either conditional (auditability, with provenance) or a regression (robustness) relative to the agent.

---

## 4. The engineering contract that makes it safe

The pattern is unsafe as "transcribe and ship." It is safe as "transcribe, ship behind an invalidation contract." Three required components:

1. **Drift canary (not a fixture test).** Periodically run *the agent* on *fresh live input* and diff its output structure against the generated code's output on the same input. Divergence beyond a threshold ⇒ artefact stale ⇒ auto-fall-back to agent mode and trigger regeneration. This is cache invalidation; without it the pattern is unsafe by construction.
2. **Fail loud, not silent.** The generated code must validate its structural assumptions (item count plausible, expected fields present, parse non-empty) and **raise** rather than emit confident garbage. The agent fails *safe* because it notices anomalies; the code must be *engineered* to fail safe — it will not do so by default.
3. **Provenance link.** The artefact records a pointer to the trajectory that generated it. Code answers *what*; the trajectory answers *why this threshold* — both are needed for audit and for regeneration.

Framed as a state machine: **explore (agent, adaptive, expensive) → transcribe (artefact + provenance) → execute (code, cheap) → canary (agent vs. code on fresh input) → on drift, back to explore.** The novel and load-bearing edge is *canary → explore*, and it is the one the naive pattern omits.

---

## 5. Relation to the evals harness already in this repo

The repo already contains the right *substrate* but is currently pointed at the wrong *target* for this pattern:

- `tests/evals/harness.py` constructs the real `Agent` as `--run` does, injects a `BufferedChannel`, and exposes rich `tool_records` / `text` / `turn_usages` via `EvalResult`. This is exactly the machinery a drift canary needs.
- `tests/evals/test_rss_count.py` runs **the agent** against a **frozen RSS fixture** and asserts tool-selection / cost / answer (the ISSUE-007 `tool_search_only` regression).

Note precisely what that eval *is*: an **agent-behaviour regression test against a frozen fixture**. By construction a frozen fixture cannot detect real-world drift — which is the *defining* failure mode of the codegen pattern. It is a unit test of the agent, not a canary for a generated artefact.

**Actionable gap:** to support the trajectory-to-code pattern, add an eval mode whose assertion target is **generated-code-output vs. agent-output on the same fresh (non-frozen) input**, not agent-output vs. a frozen number. The `BufferedChannel` / `EvalResult` plumbing is reusable as-is; only the comparison target and the input-freshness change.

---

## 6. Literature

### Closest in spirit — "do the task, then write code for the skill just acquired"

- **Voyager** (Wang et al., 2023, arXiv:2305.16291). An LLM agent that, after solving a task, writes code encoding the skill and stores it in a growing, reusable library. The right anchor for the *promise* — **but do not overclaim it as "precisely the loop."** Voyager's skills are **verified by environment feedback** (did I get the diamond?) and **accrete over many episodes** with a curriculum and a self-verification module. The bare transcription pattern has *neither* mechanism, which is exactly why the §2 critique bites. Voyager is the pattern *with* the safety machinery this proposal omits.
- **TROVE** (Wang et al., 2024) — induces a library of reusable functions from solving programmatic tasks; similar trajectory-to-code distillation. (Verify authorship before citing.)

### Code as the action space (close cousin)

- **CodeAct** — *Executable Code Actions Elicit Better LLM Agents* (Wang et al., 2024, arXiv:2402.01030). This proposal is essentially CodeAct one level up: the *final artefact* is code, not just the per-step action.
- **Code as Policies** (Liang et al., 2023, arXiv:2209.07753). Generates programs calling a fixed library of primitives — the analogue of "the same MCPs."

### Foundations of generate-code-to-solve-task

- **PAL** (Gao et al., 2022, arXiv:2211.10435); **Program of Thoughts** (Chen et al., 2022, arXiv:2211.12588); **Toolformer** (Schick et al., 2023, arXiv:2302.04761).

### The strands that name the *risk* (under-cited in casual discussion, most important here)

- **Imitation learning / behavioural cloning.** Ross & Bagnell, *A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning* (DAgger, 2011, arXiv:1011.0686). The formal account of why cloning a single trajectory compounds error off-distribution — the precise mechanism of §2. **Design against this paper, not just toward Voyager.**
- **Programming by Demonstration / Programming by Example.** Lieberman, Cypher (PBD lineage); Gulwani, *FlashFill*/PROSE (POPL 2011) as the deterministic-PBD success case. This proposal reinvents PBD with an LLM as the inducer. PBD's canonical hard problem is *generalising from one or few demonstrations*. FlashFill succeeds because it synthesises into a **constrained DSL with strong inductive bias**; the MCP/open-web case is the *unconstrained* regime PBD never fully solved. This contrast is the single most useful framing for calibrating expectations.

### Reflection / self-improvement (the substrate the pattern builds on)

- **Reflexion** (Shinn et al., 2023, arXiv:2303.11366); **Self-Refine** (Madaan et al., 2023, arXiv:2303.17651); **STaR** (Zelikman et al., 2022, arXiv:2203.14465).

### MCP specifically

No mature academic literature as of this writing; substantive material is in the protocol spec and engineering blog posts. The pattern here is largely an *engineering* contribution layered on the imitation-learning and PBD foundations above.

> Citation hygiene: Voyager, CodeAct, PAL, PoT, Toolformer, Code as Policies, Reflexion, Self-Refine, STaR, and Ross & Bagnell (DAgger) are high-confidence. TROVE and the precise PBD citations should be verified on arXiv / Semantic Scholar before formal citation.

---

## 7. Recommendations

1. **Build it — the cost/latency case is sufficient.** Adopt framing (2) (matched-MCP transcription with concrete tool-result snippets in the codegen prompt), not framing (1).
2. **Treat it explicitly as behavioural cloning.** Document the artefact as a *clone of one trajectory*, not a *compiled workflow*. Set expectations accordingly with stakeholders and in code comments.
3. **Implement the §4 contract before relying on any artefact in production:** drift canary, loud assertion failures, provenance link. The canary is the load-bearing, easily-omitted piece.
4. **Repoint the evals harness** (§5): add a generated-code-vs-agent-on-fresh-input comparison mode alongside the existing agent-vs-frozen-fixture regression tests. Reuse `BufferedChannel` / `EvalResult`.
5. **Make the judgement boundary explicit in the template.** Each implicit mental operation in the trajectory becomes *either* a deterministic helper (regex/parse) *or* an LLM subroutine call (with an LLM-generated prompt). The template should force that boundary to be declared, not left ambient.
6. **Keep the boring stuff in the template, not in generated code.** MCP client wiring, auth, retries, logging, output paths, config — never re-derived by the LLM. The LLM contributes only the workflow body and the judgement-boundary declarations.

---

## 8. Summary

The pattern is sound and the matched-MCP transcription framing is the correct design. Its honest value is **cost and latency**; its honest risk is that it is **behavioural cloning of one trajectory** and will fail *silently and confidently* under input drift. It becomes defensible — rather than merely cheap — only behind a live drift canary, loud assertion failures, and artefact→trajectory provenance. The agent run and the artefact are two phases joined by a **cache-invalidation contract**, and that contract is the part the naive version omits.
