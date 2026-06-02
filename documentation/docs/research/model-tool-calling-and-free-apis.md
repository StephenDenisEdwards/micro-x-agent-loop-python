# Reliable Tool Calling: Open Models & Free APIs

Research into which models can do **reliable tool/function calling** for this
agent, and which **free** options exist — prompted by hitting the
`gemini-2.5-flash` free-tier 20-requests/day cap (see
[ISSUE-008](../issues/ISSUE-008-gemini-free-tier-tpm-saturation.md)) and the
need for a no/low-cost path that still calls tools dependably.

**Date:** 2026-06-01
**Companion doc:** [local-model-hardware-options.md](local-model-hardware-options.md)
(hardware/VRAM focus). This doc focuses on **tool-calling reliability** and
**free hosted APIs**.

---

## TL;DR

- **`gemini-2.5-flash` cannot be self-hosted** — closed weights. Hardware
  questions only apply to *open* models that approximate it (Gemma, Qwen, Llama).
- **Reliable tool calling effectively starts at ~27–32B params.** Below 7B it is
  broken for multi-step use; this matches our own findings on `gemma3:4b` and
  `qwen2.5:7b`.
- **On the current 4 GB RTX 3050 Ti, reliable tool calling is not achievable
  locally.** The realistic self-host floor is a **24 GB GPU** (RTX 3090/4090)
  running Gemma 4 27B or Qwen3 32B.
- **You don't need to self-host to get free, reliable tool calling.** Run a big
  model on a free hosted tier: **Groq or Cerebras serving Llama 3.3 70B**
  (~97% well-formed calls, ~1,000 req/day, OpenAI-compatible).
- **The RSS ranking task needs no tool calling at all** (prompt→JSON), so it can
  use a small local model (`ollama/gemma3:4b`) or any free API today.

---

## 1. Reliability bar (Berkeley Function Calling Leaderboard, May 2026)

BFCL is the standard executable function-calling benchmark (AST-based, multi-turn
and parallel calls). Key open-weight results:

| Model | Well-formed call rate | Notes |
|-------|----------------------|-------|
| Llama 3.1 405B | 88.5% (BFCL V4 #1 open) | datacenter only |
| **Llama 3.3 70B** | **~97%** (highest reliability) | best open tool-caller; ~40 GB Q4 |
| Gemma 4 27B | ~95% | practical production minimum |
| Qwen3 32B / GLM-5.1 32B | ~93–94% | strong all-rounders |
| Qwen3-Coder 30B | ~96% code / ~91% non-code | best for code-shaped tasks |
| Qwen2.5/3 7B | malformed on multi-step | fits 8 GB, **unreliable for tools** |
| Gemma 3 4B | marginal | fits 4 GB, **not reliable for tools** |

**Compounding caveat (agentic loops):** at 95% per-call reliability an 8-step
chain succeeds end-to-end only ~66% of the time. So 95% is a floor, not comfort —
relevant to the *agent*, not to single-shot ranking.

## 2. Self-host reality vs our hardware

| Tier | Example | VRAM (Q4) | Fits our RTX 3050 Ti (4 GB)? |
|------|---------|-----------|------------------------------|
| 4B | Gemma 3 4B | ~3 GB | yes — but not reliable for tools |
| 7B | Qwen2.5 7B | ~5 GB | partial spill; not reliable for tools |
| 27–32B | Gemma 4 27B, Qwen3 32B | 16–20 GB | no — needs 24 GB GPU |
| 70B | Llama 3.3 70B | ~40 GB | no — needs 48 GB |

This corroborates [local-model-hardware-options.md](local-model-hardware-options.md):
reliable local tool calling means a dedicated 24 GB+ box (desktop RTX 3090/4090,
or a Mac Mini/Studio with unified memory). Confirmed in our own testing —
`gemma3:4b` degrades to unparseable fenced JSON past ~15 tools
([PLAN-gemma-model-support](../planning/PLAN-gemma-model-support.md)), and
`qwen2.5:7b` guesses parameters instead of reading schemas.

## 3. Free hosted APIs (the better path)

All three are OpenAI-compatible — the agent's multi-provider runtime can target
them with a base-URL + key. **Verify current limits at signup; free tiers move.**

| Provider | Free limits (approx, 2026) | Tool calling | Best model | Watch out for |
|----------|----------------------------|--------------|------------|---------------|
| **Groq** | **30,000 TPM (measured)**, ~30 RPM, ~1,000 req/day | ✅ | Llama 3.3 70B | 413/429 on **TPM** — a tool-heavy request can exceed 30k *by itself* |
| **Cerebras** | ~1M tokens/day, 30 RPM | ✅ | Llama 3.3 70B | very fast; token-budget rather than request-budget |
| **OpenRouter** | ~200 req/day per model, 20 RPM | ✅ (model-dependent) | many free | aggregator; spread load across models |

Versus `gemini-2.5-flash`'s **20 req/day**, Groq's ~1,000/day is ~50× the budget,
on a *more* reliable tool-caller (Llama 3.3 70B at ~97% vs Flash). **But the
binding free-tier limit is tokens-per-minute, and it is small.**

> **Measured (2026-06-01), not estimated.** On Groq's free tier, an agent call
> with ~60 tool schemas + system prompt + context totalled **30,253 tokens** and
> was rejected with `413 ... tokens per minute (TPM): Limit 30000`. So a single
> tool-heavy agent request can exceed the entire per-minute free budget — even
> after trimming under the 128-tool cap. And the RSS task's ~50 sequential
> ranking calls (≈5k tokens each) blew the same 30k/min budget, producing 23
> consecutive 429s in one run. **Conclusion: Groq *free* is viable only for
> small prompts — not a 60-tool agent loop, and not a 50-item batch.** Both need
> Groq Dev Tier (paid), Cerebras (larger budget), or a local model for the
> batch. See [ISSUE-009](../issues/ISSUE-009-tool-count-cap-vs-general-purpose-agent.md).

> **Data caveat:** one provider roundup listed Gemini free as "1,500 req/day".
> Our captured 429 said `quotaValue: 20`. Trust the live error / the AI Studio
> rate-limit page over third-party roundups — Google tiered the free allowance
> down and published summaries lag.

## 4. Recommendations by use case

**A) RSS ranking (`rank_model`) — no tool calling needed (prompt→JSON):**
1. `ollama/gemma3:4b` — runs today on the 4 GB GPU, $0, no cap. Good enough for
   CV-vs-job scoring (classification + short text, not tool use).
2. Groq/Cerebras Llama 3.3 70B — much higher quality, ~1,000/day free.

**B) The agent (real tool-calling loop):**
1. Groq Llama 3.3 70B — best free tool-caller; combine with tool search to stay
   under the TPM limit given the 130-tool prompt.
2. Self-host only with a 24 GB+ GPU → Gemma 4 27B / Qwen3 32B.

## Sources

- [BFCL V4 leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html) · [llm-stats BFCL](https://llm-stats.com/benchmarks/bfcl)
- [Best local models for tool calling 2026 (promptquorum)](https://www.promptquorum.com/power-local-llm/best-local-models-tool-calling-2026)
- [Free LLM APIs 2026 (klymentiev)](https://klymentiev.com/blog/free-llm-api)
- [Best open-source LLMs 2026 (Hugging Face)](https://huggingface.co/blog/daya-shankar/open-source-llms)
