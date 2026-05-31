# ISSUE-008: Gemini 2.5 Flash free-tier TPM saturation (HTTP 429)

## Date

2026-05-31

## Status

**Open.** Root cause identified from logs; mitigations proposed but not yet applied. The provider-side retry and failure-logging that this investigation produced **are** shipped (see §Related changes).

## Severity

Medium — affects only the all-Gemini profile (`config-standard-gemini-flash.json`) on Google's free tier. Anthropic profiles are unaffected (prompt caching keeps per-call billed input tiny).

## Summary

Running the agent on `config-standard-gemini-flash.json` (which routes the main
loop, Stage-2 classification, sub-agents and compaction all to
`gemini-2.5-flash`) intermittently fails with:

```
Error: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message':
'You exceeded your current quota, please check your plan and billing details...'}}
```

The binding constraint is **tokens-per-minute (TPM)**, not requests-per-minute
(RPM) or requests-per-day (RPD). The free tier for `gemini-2.5-flash` is
approximately **RPM 10 / TPM 250,000 / RPD 250** (authoritative figures are
per-project at <https://aistudio.google.com/rate-limit>; the public docs page no
longer prints a per-model table).

## Evidence (from metrics.jsonl, 28 `gemini-2.5-flash` calls, 2026-05-30/31)

| Metric | Free limit | Observed | Verdict |
|--------|-----------|----------|---------|
| Requests / day | 250 | 21 (busiest day) | far under |
| Peak requests / 60s | 10 | 5 | under |
| Peak tokens / 60s (logged) | 250,000 | 125,171 | under, but only ~2× headroom |
| Avg **input tokens per call** | — | **~23,600** | the problem |
| Tool schemas sent **every call** | — | **130** | the problem |
| Prompt caching on this profile | — | **OFF** | the problem |
| Cache-read coverage | — | 22% (Gemini implicit only) | negligible |
| Tightest call spacing | — | 2–5 s | clustered |

The successful calls all sat under every limit. The 429 itself is not in the
metrics logs (it pre-dated [the failure-logging fix](#related-changes); failed
calls emitted no metric). So TPM saturation is **inferred**, not directly
captured — see §Confirming it.

## Mechanism (why TPM saturates)

1. **Every Gemini call ships ~23k input tokens.** The bulk is **130 MCP tool
   schemas re-sent in full on every call**, plus growing conversation history.
2. **Nothing is amortised.** `PromptCachingEnabled` is `false` on this profile,
   *and* `GeminiProvider` implements no explicit context caching — it only
   *reads* Gemini's automatic implicit-cache counters (`cached_content_token_count`),
   which covered just 22% of input and was 0 on most calls. So the static
   130-schema block is re-billed on essentially every request.
3. **One agentic turn fires many of these back-to-back** (2–5 s apart). Six
   calls × 23k ≈ **140k tokens in one minute** — already past half the 250k cap
   from a single turn.
4. **Retries amplify.** Each retry re-sends the full ~23k payload, and failed
   attempts still count against TPM. Modelled at 3× retry, peak throughput rises
   to ~**375k tokens/60s — over the 250k limit.** This is the death-spiral: a
   near-limit burst trips one 429, retries push throughput further over, tripping
   more.

The agent is fundamentally an Anthropic-shaped workload (large static tool
prompt amortised by prompt caching) pointed at a provider/tier where that
amortisation does not exist.

## Confirming it (the logs can now capture this)

Thanks to the failure-logging change, the next occurrence will be recorded as a
`type: "api_call_error"` row in `metrics.jsonl` carrying `status_code`,
`error_type`, and a parsed `retry_delay_seconds`. To confirm TPM vs RPD
definitively, also inspect the full 429 body's `QuotaFailure` metric name (e.g.
`GenerateContentInputTokensPerModelPerMinute` ⇒ TPM, vs
`GenerateRequestsPerModelPerDay` ⇒ RPD) and check
<https://aistudio.google.com/rate-limit>.

## Mitigations (in order of impact, not yet applied)

1. **Cut tool schemas per call.** 130 schemas × every call is the bulk of the
   23k. Activating `tool_search` for the Gemini profile would send ~5 schemas
   instead of 130, roughly halving per-call input tokens. Tool search is
   currently gated off for non-Anthropic / cache-preserving reasons
   (`tool_search.should_activate_tool_search`); the gate would need to allow
   Gemini.
2. **Real prompt caching for Gemini.** Implement explicit `CachedContent` for
   the static system-prompt + tool-schema block in `GeminiProvider`, so it is
   billed once and referenced thereafter. Today caching is a no-op for Gemini.
3. **Stop routing the whole agent to Gemini free tier.** Point sub-agents and
   compaction at a separate-quota provider (e.g. Anthropic Haiku) to cut the
   per-turn Gemini request/token count; or upgrade to Tier 1 (billing enabled),
   which raises `gemini-2.5-flash` limits by orders of magnitude.

## Related changes

This investigation produced two shipped fixes (neither resolves the TPM
saturation itself; they make it survivable and observable):

- **Gemini retry** — `GeminiProvider.stream_chat`/`create_message` now retry on
  429 / 5xx via tenacity (fail fast on 400/403/404). Heals transient per-minute
  bursts; does **not** help an exhausted daily quota. (commit `0f5f335`)
- **Failed-call logging** — terminal LLM failures now emit a
  `type: "api_call_error"` metric + an `agent.log` warning, where previously the
  success-only metrics pipeline left 429s with no trace. (commits `889e98c`,
  `3074004`)

## Why retry alone is insufficient

Retry re-sends the same ~23k payload, so on a TPM-bound failure it can *worsen*
throughput before the minute window clears. The durable fix is reducing
per-call token volume (mitigations 1–2), not retrying harder.
