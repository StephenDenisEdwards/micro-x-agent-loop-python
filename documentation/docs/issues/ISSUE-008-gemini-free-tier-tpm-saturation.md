# ISSUE-008: Gemini 2.5 Flash free-tier request cap (HTTP 429)

> **Filename note:** the slug says "tpm-saturation" — that was the *initial
> (wrong) hypothesis*. The confirmed root cause is the **daily request cap
> (RPD)**, not tokens-per-minute. The filename is kept to preserve the index
> link and history; see §Correction.

## Date

2026-05-31 (root cause confirmed 2026-06-01)

## Status

**Open.** Root cause **confirmed from a captured 429 body**; mitigations
proposed, not yet applied. The retry and failure-logging this investigation
produced **are** shipped (see §Related changes).

## Severity

Medium — affects the all-Gemini profile (`configs/profiles/config-standard-gemini-flash.json`)
and the codegen RSS task (`rank_model: gemini/gemini-2.5-flash`) on Google's
free tier. Anthropic profiles are unaffected.

## Summary

Running on `configs/profiles/config-standard-gemini-flash.json`, or running the
`jobserve_rss_processor` `process_feed` task (which scores each job with one
Gemini call), fails with HTTP 429 `RESOURCE_EXHAUSTED`. The captured error body
(2026-06-01) names the exact quota:

```
Quota exceeded for metric:
  generativelanguage.googleapis.com/generate_content_free_tier_requests
quotaId:    GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: 20
model:      gemini-2.5-flash
```

**The binding limit is 20 `generateContent` requests per day** (per project, per
model) on the free tier for `gemini-2.5-flash`. It is **not** tokens-per-minute,
not requests-per-minute, and not the 250/day figure older docs cite — Google has
tiered the free allowance down to **20/day**. (Authoritative per-project values:
<https://aistudio.google.com/rate-limit>.)

## Why it trips so fast

- **The RSS `process_feed` task scores one job per LLM call, in a sequential
  loop.** A ~50-job feed = ~50 requests in one run against a **20/day** ceiling,
  so ~30 jobs 429 and the run can fail outright. Because failed jobs are not
  stored, a fully-over-budget run writes **no sidecar and no report at all**.
- **The agent's own Gemini calls share the same per-project/day bucket** — main
  loop, Stage-2, etc. — so the 20 is often partly spent before the task even
  runs.
- One call = one request regardless of size; token volume is irrelevant to
  *this* quota.

## Correction (the earlier TPM hypothesis was wrong)

The first version of this issue concluded **TPM saturation** (≈250k tokens/min).
That was **inference from a success-only dataset** — the metrics pipeline logged
only successful calls, so every 429 was invisible and the analysis reasoned from
call sizes (~23k input tokens, 130 uncached tool schemas) and clustering to a
plausible-but-wrong mechanism. Three successive guesses (RPD 250 → TPM → RPM 10)
were all overturned once the **actual 429 body was captured** and named
`GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue 20`.

Lesson: a success-only log cannot diagnose failures. The fix was to capture the
failures (see §Related changes); the answer appeared immediately once we did.

The per-call token detail from that earlier analysis is still accurate and still
*relevant* (large prompts make a Tier-1 upgrade or batching more attractive),
but it is **not** what causes the 429.

## Mitigations (in order of impact, not yet applied)

1. **Batch the scoring loop.** Score N jobs per LLM call instead of one. At ~10
   jobs/call, a 50-job feed = ~5 requests, comfortably under 20/day. This is the
   structural fix that makes the task viable on free tier. Lives in
   `tools/jobserve_rss_processor/src/task.ts` (`assessJob` loop).
2. **Fail fast on daily-quota 429s; only retry per-minute limits.** The current
   Gemini retry predicate retries *any* 429, including this daily one — wasting
   the 5-attempt budget over minutes on an error that won't clear until midnight
   Pacific. Gate on the `quotaId`: retry `...PerMinute`, fail fast on `...PerDay`.
3. **Use a higher-quota provider for ranking.** The ranking call needs **no tool
   calling** (prompt→JSON), so it can use any capable text model:
   - `ollama/gemma3:4b` — local, $0, no cap (runs on the 4GB RTX 3050 Ti).
   - Groq / Cerebras free tier (Llama 3.3 70B) — ~1,000 req/day, far higher
     quality. See [model-tool-calling-and-free-apis](../research/model-tool-calling-and-free-apis.md).
4. **Enable billing (Tier 1).** Raises `gemini-2.5-flash` RPD by orders of
   magnitude; the cap effectively disappears.

## Related changes

This investigation produced two shipped fixes (neither resolves the quota cap;
they made it survivable and — crucially — observable):

- **Gemini retry** — `GeminiProvider.stream_chat`/`create_message` retry on
  429 / 5xx via tenacity, fail fast on 400/403/404. Heals transient per-minute
  bursts; does **not** help an exhausted daily quota. (commit `0f5f335`)
  *Refinement still needed — mitigation 2 above.*
- **Failed-call logging, two layers:**
  - Agent side: terminal LLM failures emit a `type: "api_call_error"` metric +
    `agent.log` warning. (commits `889e98c`, `3074004`)
  - Task-subprocess side: `_runtime/src/llm.ts` emits a `__LLM_ERROR__:` stderr
    sentinel per failed call (status, `retry_delay_seconds`, **`quota_metric`**);
    codegen `run_task` parses it into `structuredContent._llm_errors` + a banner.
    **This is what captured the definitive quota name.** (commit `77f74e0`)

## Why retry alone is insufficient

This is a **daily** quota. Retry with second-scale backoff cannot clear it —
the window resets at midnight Pacific. Retrying just burns the attempt budget
and still fails. The durable fixes are batching (mitigation 1) and/or a
different provider/tier (3–4).
