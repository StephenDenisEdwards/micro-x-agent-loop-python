# Plan: Google Gemma Model Support

**Status:** Draft
**Date:** 2026-05-26

**Goal:** Make Google's Gemma family (Gemma 2, Gemma 3) usable as a first-class
model with the agent — including tool calling — across all three viable runtimes
(Ollama, OpenAI-compatible local servers, and Google's hosted Gemma endpoint),
documenting which features degrade and which features have to be polyfilled.

This is not a port to a new provider in the same sense as `PLAN-multi-provider.md`.
Gemma's wire format is reachable through three providers we already have. The
real work is in compensating for two architectural mismatches between Gemma and
the agent's contract.

---

## 1. Why

- **Open weights, local-first.** Gemma is the strongest Google-licensed
  open-weights family. Running it locally (Ollama / vLLM / llama.cpp) means
  zero per-token cost, full privacy, and the ability to run offline.
- **Long context at small sizes.** Gemma 3 ships 128K context on the 4B / 12B /
  27B variants — competitive with the cloud frontier at a fraction of the cost.
- **Multimodality (Gemma 3 4B+).** Image input becomes possible without paying
  Anthropic / OpenAI cloud rates.
- **Coverage of the "small local model" tier.** Gemma 3 1B / 4B are credible
  candidates for sub-agent and classifier roles (see `RoutingPolicies`), where
  cost / latency dominate quality.
- **Hosted Gemma as a no-cost cloud path.** Google AI Studio and Vertex AI both
  serve Gemma via the same `google-genai` SDK the agent already uses for
  Gemini — meaning a working cloud path exists today with one provider tweak.

### Baseline: what already exists

There is no `GemmaProvider`. Gemma support today is purely config-driven on
top of the existing `OllamaProvider`:

- `config-standard-ollama-gemma2.json` — runs `gemma2:2b` through Ollama's
  OpenAI-compatible endpoint
- `config-standard-ollama-gemma2-hybrid.json` — same model for the main loop,
  Anthropic Haiku for sub-agents, compaction, and Stage 2 classification
- Pricing entry `"ollama/gemma2:2b"` (zero-cost) in `config-base.json`
- Context-window entry `"gemma2": 8_000` in `constants.py`

Both profiles explicitly disable tool calling (`ToolSearchEnabled: "false"`),
sub-agents, mode analysis, Stage 2 classification, and tool-result
summarization. That is the gap this plan closes: getting those features back
on for Gemma 3, and adding the cloud (Path C) and self-hosted (Path B) paths
that don't exist today.

---

## 2. The Two Structural Mismatches

These are the reason a "just add a config file" approach is insufficient. Both
mismatches must be handled somewhere — provider, system prompt, or both.

### 2.1 No Native Function-Calling Grammar

Anthropic, OpenAI, and Gemini all have a trained-in tool-call format: the model
emits structured fields (`tool_use` blocks, `tool_calls[]`, `FunctionCall` parts)
that the SDK surfaces as typed objects. `TurnEngine` consumes that typed shape.

**Gemma was not trained on a structured tool-call template.** It will happily
hallucinate JSON when asked, but there is no contract that the JSON will be
well-formed, fenced, or distinguishable from prose. Empirically:

| Variant | Native tool calling? | Notes |
|---------|----------------------|-------|
| Gemma 2 (all sizes) | ❌ No | Pre-dates Google's tool-call training data |
| Gemma 3 1B | ❌ No | Instruction-tuned but not for tool use |
| Gemma 3 4B / 12B / 27B | ⚠️ Partial | Trained on some function-calling data; reliability varies by serving layer |

What "reliability varies by serving layer" means:

- **Ollama** advertises `tools` on its OpenAI-compatible endpoint for any model,
  but for Gemma it works by wrapping a prompted tool-call template around the
  model. Result quality is uneven — small Gemma models routinely emit invalid
  JSON, drop the wrapper, or call a tool that doesn't exist.
- **vLLM** lets you specify `--tool-call-parser` (e.g. `hermes`, `pythonic`,
  `jamba`) plus a `--chat-template` Jinja file. Picking the parser that matches
  the chat template is mandatory; mismatched parser silently returns an empty
  tool-calls list. There is no out-of-the-box Gemma parser yet, so the user
  must either pick `pythonic` and accept the leakage, or write a custom parser.
- **Google AI Studio (`google-genai`)** serves Gemma 3 via the same Gemini
  endpoint and *does* normalise tool calls to `FunctionCall` parts. This is the
  most reliable path but requires network + API key (free tier exists).

### 2.2 No `system` Role in the Chat Template

Gemma's chat template only knows `user` and `model` turns. There is no `system`
slot. Serving layers handle this two different ways:

- **Ollama / vLLM via OpenAI-compatible** silently prepend the system message
  into the first user turn. This works for short system prompts but the agent's
  system prompt is large (memory directive + tool-search directive + sub-agent
  directive + task-decomposition directive + dynamic date / OS info). Folded
  in, it dominates the first turn and pushes user content far down — small
  Gemma variants lose track of the actual question.
- **`google-genai`** accepts `system_instruction=` and handles the mapping
  internally, similar to Gemini. Same path as the existing GeminiProvider.

This is why the existing `config-standard-ollama-gemma2.json` sets
`PromptCachingEnabled: false`, disables tool search, disables mode analysis,
and disables sub-agents — every one of those features depends on either tool
calling working or the system prompt being honoured.

---

## 3. Three Runtime Paths

The plan delivers all three; each is a phase. Users pick based on their
constraints (local vs cloud, model size, latency).

| Path | Provider used | Tool calling | System prompt | Cost | Best for |
|------|---------------|--------------|---------------|------|----------|
| **A. Ollama** | `ollama` (exists) | Prompted (server-side) | Prepended to user turn | $0 | Local dev, single-user, gemma2:2b / gemma3:4b |
| **B. OpenAI-compatible (vLLM / LM Studio / llama.cpp)** | `openai-compatible` (PLAN-local-model-ecosystems Phase 1) | Prompted via parser flag | Prepended to user turn | $0 (own GPU) | Self-hosted production, gemma3:12b / 27b |
| **C. Google AI / Vertex** | `gemini` (exists, retargeted) | Native via SDK | `system_instruction=` | $0 free tier, otherwise Vertex prices | Cloud, no GPU needed, gemma3:27b-it |

Paths A and C work without any new provider code. Path B depends on
[PLAN-local-model-ecosystems.md](PLAN-local-model-ecosystems.md) Phase 1.

---

## 4. Implementation

### Phase 1 — Path C (Google-hosted Gemma via existing GeminiProvider)

This is the smallest useful change and gives the agent a *working* Gemma path
with real tool calling on day one. Two edits:

**4.1 Allow the Gemini provider to address Gemma model IDs.** The
`GeminiProvider.stream_chat()` already passes `model=` straight through to
`client.aio.models.generate_content_stream(model=model_id, ...)` (see
`providers/gemini_provider.py:185`). Gemma 3 model IDs like
`gemma-3-27b-it` resolve on the same endpoint. No code change in the provider
itself — just verify with a smoke test that `model="gemma-3-27b-it"` returns
a `FunctionCall` part for a tool-using prompt.

**4.2 New profile config — `config-standard-gemma-cloud.json`:**

```json
{
  "Base": "config-base.json",
  "Provider": "gemini",
  "Model": "gemma-3-27b-it",
  "MaxTokens": 4096,
  "PromptCachingEnabled": false,
  "SubAgentProvider": "gemini",
  "SubAgentModel": "gemma-3-4b-it",
  "CompactionStrategy": "summarize",
  "CompactionProvider": "gemini",
  "CompactionModel": "gemma-3-4b-it"
}
```

**4.3 Pricing entries in `config-base.json`** — Google's Gemma API tier is
free for now, but record explicit zero entries so the unknown-model warning
doesn't fire:

```json
"gemini/gemma-3-1b-it":  { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"gemini/gemma-3-4b-it":  { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"gemini/gemma-3-12b-it": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"gemini/gemma-3-27b-it": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 }
```

**4.4 Context-window entry in `src/micro_x_agent_loop/constants.py`** — the
`MODEL_CONTEXT_WINDOW` dict drives compaction triggering. Add:

```python
"gemma-3-1b-it":  32_000,
"gemma-3-4b-it":  128_000,
"gemma-3-12b-it": 128_000,
"gemma-3-27b-it": 128_000,
```

That is the entire Phase 1 — no new provider, no new factory branch.

### Phase 2 — Path A hardening (Ollama / Gemma 3, with tool calling on)

Phase 2 makes the existing local Ollama path actually usable end-to-end,
not just the chat-only stub it is today.

**4.5 New profile config — `config-standard-ollama-gemma3.json`:**

```json
{
  "Base": "config-base.json",
  "Provider": "ollama",
  "Model": "gemma3:4b",
  "ApiKey": "unused",
  "MaxTokens": 2048,
  "PromptCachingEnabled": false,
  "CompactionStrategy": "summarize",
  "SubAgentsEnabled": false,
  "ModeAnalysisEnabled": false,
  "Stage2ClassificationEnabled": false,
  "ToolSearchEnabled": "false",
  "ToolResultSummarizationEnabled": false,
  "SystemPromptVariant": "compact"
}
```

The `SystemPromptVariant: "compact"` field is new — see 4.7.

**4.6 Ollama tool-call reliability gate.** `OllamaProvider` already sets
`tool_choice="auto"` when tools are present (see `ollama_provider.py:43`).
For Gemma, this is necessary but not sufficient; the model still emits
malformed tool calls a non-trivial fraction of the time. Add a single
defensive parse layer in `OllamaProvider._build_stream_kwargs()` or a thin
post-processor on the assistant message:

- If the model returns text content that looks like a fenced JSON tool call
  but the OpenAI-compatible response did not surface it in `tool_calls[]`,
  log it as `gemma_unparsed_tool_call` and treat the turn as text-only.
- Do not attempt to re-parse and inject a synthetic tool call. The risk
  of acting on a hallucinated tool name outweighs the benefit. Let the
  model retry on the next turn.

This is a metrics-only intervention — surface the failure rate so users
can see whether their chosen Gemma size is large enough for the workload.

**4.7 Compact system prompt variant.** Add a `SystemPromptVariant` field
(`"full"` (default) | `"compact"`) to `agent_config.py` and route it
through `bootstrap.py` to `system_prompt.py`. The compact variant strips:

- `_TOOL_SEARCH_DIRECTIVE` (irrelevant when `ToolSearchEnabled=false`)
- `_SUBAGENT_DIRECTIVE` (irrelevant when `SubAgentsEnabled=false`)
- `_TASK_DECOMPOSITION_DIRECTIVE`
- User memory guidance (kept only if `MemoryEnabled=true`)
- The date / OS info preamble (Gemma local models don't need it)

This is also useful for the existing `tool_search_only` and
`system_prompt: "compact"` routing-policy overrides — making the directive
trim path explicit means RoutingPolicies and SystemPromptVariant agree on
what "compact" produces.

### Phase 3 — Path B (OpenAI-compatible servers)

Depends on [PLAN-local-model-ecosystems.md](PLAN-local-model-ecosystems.md)
Phase 1 (the generic `openai-compatible` provider). Once that exists:

**4.8 New profile config — `config-standard-gemma-vllm.json`:**

```json
{
  "Base": "config-base.json",
  "Provider": "openai-compatible",
  "Model": "google/gemma-3-12b-it",
  "ProviderBaseUrl": "http://localhost:8000/v1",
  "ProviderApiKeyOptional": true,
  "MaxTokens": 4096,
  "PromptCachingEnabled": false,
  "SystemPromptVariant": "compact",
  "ProviderOverrides": {
    "tool_choice": "auto"
  }
}
```

**4.9 Document the vLLM launch line** in
`documentation/docs/operations/multi-provider-setup.md`. The user is
responsible for picking `--tool-call-parser` and `--chat-template` correctly:

```bash
vllm serve google/gemma-3-12b-it \
  --tool-call-parser pythonic \
  --chat-template ./gemma3-chat-template.jinja \
  --enable-auto-tool-choice
```

The agent does not validate this — if the parser is wrong, tool calls
silently disappear and the agent will loop on text-only responses.

### Phase 4 — Optional: native GemmaProvider

Only build this if Paths A–C all prove insufficient. A dedicated
`GemmaProvider` would do prompted tool calling client-side: inject a
strict JSON-schema-with-fences directive into the system prompt, then
parse the assistant text deltas for tool-call fences and surface them
as `tool_use` blocks to `TurnEngine`. This is a substantial commitment
(parser correctness, schema injection, streaming-safe parse) and should
be deferred until the simpler paths have been tried and measured.

The exit criteria for *not* building Phase 4: Phase 1 (Path C) covers the
hosted use case, and Phase 2 + Phase 3 give acceptable tool-call success
rates on the 12B / 27B local variants. If success rate on the local 12B
falls below ~70% on the behavioural eval suite
([PLAN-behavioural-eval-suite.md](PLAN-behavioural-eval-suite.md)),
revisit Phase 4.

---

## 5. Feature Compatibility Matrix

What works, what degrades, what's off — per runtime path. This is the
table users need to make an informed config choice.

| Feature | Path A (Ollama) | Path B (vLLM) | Path C (Google) |
|---------|-----------------|---------------|-----------------|
| Streaming text | ✅ | ✅ | ✅ |
| Tool calling | ⚠️ Unreliable on 1B–4B; OK on 12B+ | ⚠️ Depends on parser config | ✅ Native |
| Parallel tool calls | ❌ | ⚠️ Parser-dependent | ✅ |
| Prompt caching | ❌ (Ollama has none) | ⚠️ vLLM prefix cache, server-side, not surfaced | ⚠️ Gemini auto cache may apply |
| System prompt fidelity | ⚠️ Folded into user turn | ⚠️ Folded into user turn | ✅ `system_instruction=` |
| Sub-agents | ⚠️ Disable on 1B–4B | ✅ on 12B+ | ✅ |
| Mode analysis (Stage 1+2) | ❌ Disable | ⚠️ 12B+ only | ✅ |
| Tool search (semantic) | ❌ Disable | ⚠️ Needs embedding model | ⚠️ Use separate embedder |
| Compaction (summarize) | ✅ Quality varies | ✅ | ✅ |
| Mutating tools (HITL) | ✅ | ✅ | ✅ |
| Vision (image input) | ✅ gemma3:4b+ | ✅ gemma3:4b+ | ✅ gemma-3-4b-it+ |
| 128K context | ✅ gemma3:4b+ | ✅ | ✅ |

Cells marked ⚠️ mean "works but with a caveat documented above" — those
caveats are the reason the per-profile config disables specific features.

---

## 6. Tool-Calling Contract Differences (Detail)

This is the meat of the plan — what the agent contract assumes and how Gemma
breaks each assumption.

### 6.1 What `TurnEngine` expects

Looking at the existing providers, `TurnEngine` consumes a uniform internal
shape:

```python
message = {"role": "assistant", "content": [
  {"type": "text", "text": "..."},
  {"type": "tool_use", "id": "<stable-id>", "name": "<tool>", "input": {...}},
]}
stop_reason = "tool_use" | "end_turn" | "max_tokens"
```

Provider responsibilities (`PLAN-multi-provider.md` §3–4):
1. Surface `tool_use` blocks with a stable ID per call
2. Set `stop_reason="tool_use"` when there is at least one tool call
3. Match tool-result turns back to their tool calls via the same ID

### 6.2 What Gemma + each runtime actually delivers

| Concern | Anthropic / OpenAI / Gemini contract | Gemma actual |
|---------|--------------------------------------|--------------|
| Tool-call delimiter | SDK typed object | Free-form text, varies by template |
| Stable call ID | Provided by API | None — must synthesise (uuid4, same as Gemini provider already does) |
| Parallel calls in one turn | Supported | Template-dependent; Ollama serialises, vLLM `pythonic` parser supports it |
| Tool-name validation | API rejects unknown names | Model can call any string — agent must reject unknown names with a tool_result error and let the model retry |
| Argument shape | API enforces against schema | Free-form JSON — may be missing required fields, may include extras |
| Truncated tool call | Surfaces as parse error | Returns as text content; never marked as a tool call |

**Synthetic ID strategy** already exists in `GeminiProvider` (see
`gemini_provider.py:204` — `uuid.uuid4()` per call). Both Ollama's
OpenAI-compatible response and Gemini's `FunctionCall` parts get the same
treatment. No new code required for this on Paths A and C.

**Unknown-tool-name rejection** is the one new agent-side check Phase 2
should add: in `TurnEngine`, when an assistant turn contains a `tool_use`
naming a tool that isn't in the current tool registry, emit a synthetic
`tool_result` block with `is_error=True` and a message like:
`"Unknown tool 'foo'. Available tools: ..."`. This already happens
implicitly when the tool dispatcher fails to find a handler, but the
error message for Gemma needs to be model-readable (it'll feed back into
the next turn) rather than just logged.

### 6.3 Tool-result message format

All three paths consume the same `{"type": "tool_result", "tool_use_id": ...,
"content": "..."}` user blocks the existing providers convert. No change.

---

## 7. Config Schema Additions

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `SystemPromptVariant` | `"full" \| "compact"` | `"full"` | Strip directives unusable on small local models (Phase 2) |
| `ProviderOverrides` | `dict[str, Any]` | `{}` | Forward server-specific kwargs (e.g. `tool_choice`) — already proposed by PLAN-local-model-ecosystems Phase 3 |

No new top-level `Provider` value is required for Gemma. Path A uses
`"ollama"`, Path B uses `"openai-compatible"`, Path C uses `"gemini"`.

---

## 8. Files Summary

### Created

| File | Phase | Purpose |
|------|-------|---------|
| `config-standard-gemma-cloud.json` | 1 | Google AI Studio / Vertex AI Gemma 3 profile |
| `config-standard-ollama-gemma3.json` | 2 | Local Gemma 3 via Ollama |
| `config-standard-gemma-vllm.json` | 3 | vLLM-served Gemma 3 |
| `tests/providers/test_gemma_via_gemini.py` | 1 | Smoke test that `GeminiProvider` accepts Gemma model IDs and surfaces FunctionCall parts |
| `tests/providers/test_gemma_via_ollama.py` | 2 | Tool-call reliability fake-stream test for the Ollama+Gemma path |
| `documentation/docs/operations/gemma-setup.md` | 1–3 | Per-runtime setup guide, picking a Gemma size, the feature matrix |

### Modified

| File | Phase | Change |
|------|-------|--------|
| `config-base.json` | 1 | Pricing zero entries for Gemma 3 variants; context-window entries |
| `src/micro_x_agent_loop/constants.py` | 1 | `MODEL_CONTEXT_WINDOW` additions for Gemma 3 |
| `src/micro_x_agent_loop/agent_config.py` | 2 | `system_prompt_variant: str = "full"` field |
| `src/micro_x_agent_loop/system_prompt.py` | 2 | Branch on variant; emit compact form |
| `src/micro_x_agent_loop/bootstrap.py` | 2 | Thread `SystemPromptVariant` into `build_system_prompt()` |
| `src/micro_x_agent_loop/providers/ollama_provider.py` | 2 | Log `gemma_unparsed_tool_call` metric when text-only response contains tool-call-looking content |
| `src/micro_x_agent_loop/turn_engine.py` | 2 | Reject unknown tool names with a model-readable `tool_result` error |
| `documentation/docs/operations/multi-provider-setup.md` | 3 | vLLM launch line; pointer to new gemma-setup.md |

### Documentation only

- `documentation/docs/planning/INDEX.md` — add this plan to the Priority Queue
- `documentation/docs/architecture/decisions/` — *no new ADR required*; this
  plan reuses existing provider abstractions. Add an ADR only if Phase 4
  (native GemmaProvider) is approved.

---

## 9. Testing

| Test | Phase | What it covers |
|------|-------|----------------|
| `test_gemma_via_gemini_streams_text` | 1 | `GeminiProvider.stream_chat(model="gemma-3-4b-it")` returns text deltas and a valid `UsageResult` |
| `test_gemma_via_gemini_returns_function_call` | 1 | Hosted Gemma surfaces a `FunctionCall` part for a tool-using prompt (smoke; requires `GEMINI_API_KEY`) |
| `test_pricing_entries_complete` | 1 | All Gemma model IDs in profile configs resolve to a pricing entry |
| `test_context_window_lookup` | 1 | Compaction trigger reads the right context size for `gemma-3-*-it` |
| `test_system_prompt_compact_variant` | 2 | `build_system_prompt(variant="compact")` omits the four heavy directives |
| `test_turn_engine_rejects_unknown_tool` | 2 | Unknown tool name → model-readable `tool_result` error, not silent failure |
| `test_ollama_logs_unparsed_tool_call` | 2 | Ollama assistant text containing a JSON tool-call fence without a parsed `tool_call` increments the metric |
| `test_create_provider_routes_gemma_paths` | 1, 3 | `create_provider("gemini")` for Path C, `create_provider("openai-compatible")` for Path B |

Manual test docs: `documentation/docs/testing/MANUAL-TEST-gemma-cloud.md`,
`MANUAL-TEST-gemma-ollama.md`. Each should run a known-good prompt that
exercises a tool call and check the agent does not loop on it.

---

## 10. Implementation Sequence

```
Phase 1   Google-hosted Gemma via existing GeminiProvider   (smallest useful change)
            - new config profile, pricing, context window entries
            - smoke test against gemma-3-27b-it
            - documentation: gemma-setup.md (Path C section)

Phase 2   Ollama hardening for Gemma 3                       (depends on Phase 1 docs)
            - SystemPromptVariant=compact
            - unknown-tool-name rejection in TurnEngine
            - unparsed tool-call metric in OllamaProvider
            - config-standard-ollama-gemma3.json profile
            - documentation: gemma-setup.md (Path A section)

Phase 3   Path B (vLLM / OpenAI-compatible)                  (depends on PLAN-local-model-ecosystems Phase 1)
            - config-standard-gemma-vllm.json profile
            - vLLM launch-line documentation
            - ProviderOverrides {tool_choice: auto}

Phase 4   Native GemmaProvider                                (only if Phases 1–3 insufficient)
            - prompted tool calling with JSON-fence parser
            - streaming-safe parse state machine
            - requires a new ADR
```

Phase 1 is the minimum viable change. Phases 2 and 3 are independent of each
other after Phase 1. Phase 4 is contingent on measured outcomes.

---

## 11. Open Questions

| Question | Answer needed before | Notes |
|----------|---------------------|-------|
| Does Google AI Studio's free tier actually accept `gemma-3-27b-it`, or only via Vertex AI billing? | Phase 1 smoke test | If billing-only, downgrade Phase 1 default to `gemma-3-4b-it` |
| What is the tool-call success rate of `gemma3:12b` on Ollama for the agent's real tool schema (not toy examples)? | Phase 2 | Run the eval harness from PLAN-behavioural-eval-suite once it exists |
| Does Gemini auto-cache fire for Gemma model IDs, or only Gemini-branded ones? | Phase 1 metrics review | Check `usage_metadata.cached_content_token_count` on hosted Gemma turns |
| Should the compact system-prompt variant be tied to `Provider` rather than an explicit flag? | Phase 2 | Tying to provider couples concerns; explicit flag is clearer but requires user knowledge |
| Vision input path — does the existing `tool_result` content shape carry images correctly through the Gemini SDK for Gemma? | Phase 1+ | Out of scope for tool calling but worth checking once the basic path is live |

---

## 12. Non-Goals

- **Fine-tuning Gemma for the agent's tool schema.** Possible (Gemma supports
  LoRA / SFT) but a separate, much larger project.
- **A Gemma-specific TurnEngine variant.** All paths still produce the same
  internal message shape; the engine stays unchanged.
- **Replacing Anthropic / OpenAI for cost reasons.** This plan is about
  *enabling* Gemma, not about making it the default — pricing and quality
  benchmarks for that decision belong in `PLAN-cost-reduction.md`.
- **Supporting Gemma 1.** Two generations behind; not worth the porting cost.
