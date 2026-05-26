# Plan: Google Gemma Model Support

**Status:** Draft
**Date:** 2026-05-26 (revised to centre on `gemma3:4b` for local use; further revised to remove already-implemented work and reuse existing config fields)

**Goal:** Make Google's Gemma family (Gemma 2, Gemma 3) usable as a first-class
model with the agent — including tool calling — across all three viable runtimes
(Ollama, OpenAI-compatible local servers, and Google's hosted Gemma endpoint),
documenting which features degrade and which features have to be polyfilled.

**Headline local target:** `gemma3:4b` (Q4_K_M, ~3GB) — the largest Gemma 3
variant that fits fully in 4GB VRAM on Ampere-class consumer GPUs (e.g. RTX
3050 Ti).

**Gemma 4 e2b at Q4_K_M does not fit either** (verified 2026-05-26 against
published Ollama spec tables): GGUF file is 3.11GB on disk but the published
minimum VRAM to run it is 6GB, recommended 8GB — driven by activation memory
and KV cache, not just weights. On a 4GB GPU you'd have to drop to a 2-bit
or 3-bit quant (e.g. `UD-IQ2_M`, `UD-Q2_K_XL`), which gives up enough quality
that `gemma3:4b` Q4_K_M is the better choice on this hardware. Gemma 4
paths therefore remain out of scope for this plan regardless of quantisation
on 4GB-class GPUs, and will be covered in a follow-up plan for users with
≥8GB VRAM once Ollama / vLLM ship stable tool-call templates for Gemma 4.

Sources for the Gemma 4 VRAM check:
- knightli.com 2026-05-01 quantisation table — e2b Q4_K_M: 3.11GB file, 6GB min VRAM, 8GB safer
- oflight.co.jp 2026 hardware guide — corroborates 5–6GB minimum for Q4 e2b

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
summarization. Note that the existing profiles **already** receive the compact
system prompt today — `bootstrap.py:208` and `server/agent_manager.py:154` both
hardcode `compact=app.provider_name == "ollama"`. That hardcode is what this
plan replaces with an explicit config field (see 4.7). The substantive gap
this plan closes: getting tool calling back on for Gemma 3, and adding the
cloud (Path C) and self-hosted (Path B) paths that don't exist today.

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
| Gemma 3 4B | ⚠️ Marginal | Emits `<tool_call>` XML tags correctly with ≤15 tools; degrades to fenced JSON in code blocks at 15–22+ tools; strong bias toward over-eager tool calls on conversational prompts |
| Gemma 3 12B / 27B | ⚠️ Partial | Trained on some function-calling data; reliably emits `<tool_call>` blocks across larger tool registries |
| `orieg/gemma3-tools:4b-ft` | ✅ (claimed) | Community fine-tune of Gemma 3 4B for tool calling; consider as drop-in replacement for `gemma3:4b` if base model fails the eval |

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
| **A. Ollama** | `ollama` (exists) | Prompted (server-side) via `<tool_call>` XML | Prepended to user turn | $0 | Local dev, 4GB-VRAM GPUs, **`gemma3:4b` is the primary target** |
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
"gemini/gemma-3-27b-it": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/gemma3:4b":                     { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/gemma3:12b":                    { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/gemma3:27b":                    { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/orieg/gemma3-tools:4b-ft":      { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 }
```

(Existing precedent: `config-base.json:210` has `ollama/gemma2:2b` at zero —
without these entries the unknown-model pricing warning fires every session.)

**4.4 Context-window entry in `src/micro_x_agent_loop/constants.py`** — the
`TOOL_SEARCH_CONTEXT_WINDOWS` dict (consumed by `tool_search.py:58` via
`_get_context_window()`) controls *tool-search activation thresholds*. It is
prefix-matched (`model.startswith(prefix)`), and the existing `"gemma2": 8_000`
entry does **not** match `gemma3:*` or `gemma-3-*-it`, so without these
additions Gemma 3 falls through to the 200k default and tool-search auto
sizing is wrong. Add:

```python
"gemma3":         128_000,   # Ollama IDs (gemma3:4b, gemma3:12b, ...)
"gemma-3-1b-it":  32_000,
"gemma-3-4b-it":  128_000,
"gemma-3-12b-it": 128_000,
"gemma-3-27b-it": 128_000,
```

Note: compaction triggering is controlled by `CompactionThresholdTokens`
(default 80k, configured in `config-base.json`), **not** by this dict. The
dict only affects when "auto" tool search activates.

That is the entire Phase 1 — no new provider, no new factory branch.

### Phase 2 — Path A hardening (Ollama / `gemma3:4b`, with tool calling on)

Phase 2 makes the existing local Ollama path actually usable end-to-end on
the headline target `gemma3:4b`, not just the chat-only stub it is today.
The provider already advertises `tool_choice="auto"`; the work here is in
narrowing the tool surface and instructing the model so its 4B-scale
tool-calling reliability lands inside the usable envelope (see §6.4).

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
  "ToolSearchEnabled": "true",
  "ToolSearchMaxLoad": 12,
  "ToolResultSummarizationEnabled": false,
  "SystemPromptCompact": true,
  "SystemPromptExtras": [
    "Only call a tool when the user asks you to perform an action. For questions, explanations, or small talk, respond in plain text."
  ]
}
```

Two deliberate departures from the previous draft of this profile:

1. **`ToolSearchEnabled: "true"` with `ToolSearchMaxLoad: 12`** — empirically
   `gemma3:4b` emits valid `<tool_call>` XML up to ~15 exposed tools, then
   degrades to fenced JSON that Ollama does not parse as a tool call. Capping
   the exposed surface via the **existing** `tool_search_max_load` field
   (`agent_config.py:149`, default 5; `tool_search.py:202` caps semantic
   top_k by it, `tool_search.py:249` caps keyword results by it) keeps every
   turn inside the envelope. The full registry remains discoverable via
   `tool_search`, but only ≤12 tools are bound at once. **No new config
   field is required** — the cap mechanism already exists.
2. **`SystemPromptExtras`** — `gemma3:4b` has a strong bias toward emitting
   tool calls even for conversational prompts. The explicit "only when asked
   to act" instruction measurably reduces spurious tool calls on greetings,
   acks, and clarification turns. See §6.4 for the failure modes this
   suppresses.

The `SystemPromptCompact: true` field is new in the *config surface* but the
underlying behaviour already exists — see 4.7. The `SystemPromptExtras` field
is new — it appends model-specific guidance after the core directives without
baking it into `system_prompt.py`.

**Fallback option:** if the eval gate in §11 finds `gemma3:4b` tool-call
success below the bar, swap `"Model": "orieg/gemma3-tools:4b-ft"` (community
fine-tune for tool calling). Same wire format, same VRAM budget — only the
weights differ.

**4.6 Ollama tool-call reliability metric.** `OllamaProvider` already sets
`tool_choice="auto"` when tools are present (see `ollama_provider.py:43`).
For Gemma, this is necessary but not sufficient; the model still emits
malformed tool calls a non-trivial fraction of the time. Add a defensive
inspection of the assembled assistant message after streaming completes.

`OllamaProvider` currently overrides nothing related to parsing — it only
adds `tool_choice` in `_build_stream_kwargs()`. To inspect the assistant
text, override the `_finalise_message()` hook in `OpenAIProvider` (add it
if missing) or post-process inside `OllamaProvider.stream_chat()` after
the upstream call returns:

- If the model returns text content that looks like a fenced JSON tool call
  but the OpenAI-compatible response did not surface it in `tool_calls[]`,
  log it as `gemma_unparsed.fenced_json` and treat the turn as text-only.
- If the text contains an unclosed `<tool_call>` block, log it as
  `gemma_unparsed.bare_xml`.
- Do not attempt to re-parse and inject a synthetic tool call. The risk
  of acting on a hallucinated tool name outweighs the benefit. Let the
  model retry on the next turn.

This is a metrics-only intervention — surface the failure rate so users
can see whether their chosen Gemma size is large enough for the workload.

**4.7 Expose the compact system prompt as explicit config.** The compact
variant **already exists** — `system_prompt.py:513` accepts `compact: bool`
and already strips `_TOOL_SEARCH_DIRECTIVE`, `_SUBAGENT_DIRECTIVE`,
`_TASK_DECOMPOSITION_DIRECTIVE`, `_USER_MEMORY_GUIDANCE`, the codegen
directive, the FS-navigation directive, and the web-access directive when
`compact=True`. The gap is in the *config surface*: both `bootstrap.py:208`
and `server/agent_manager.py:154` hardcode
`compact=app.provider_name == "ollama"`.

Changes needed:

1. Add `system_prompt_compact: bool | None = None` to `agent_config.py`
   (tri-state: `None` = preserve current behaviour for back-compat, `True`
   = force compact, `False` = force full).
2. In `bootstrap.py:208` and `server/agent_manager.py:154`, replace the
   hardcode with: `compact=app.system_prompt_compact if app.system_prompt_compact is not None else (app.provider_name == "ollama")`.
3. Parse `SystemPromptCompact` from config in `app_config.py`.

This change is also useful for the existing `tool_search_only` and
`system_prompt: "compact"` routing-policy overrides (`agent_builder.py:148`)
— exposing the field explicitly means RoutingPolicies and the profile config
agree on what "compact" produces.

The `SystemPromptExtras` field is genuinely new: a `list[str]` appended to
the rendered system prompt after the core directives, plumbed through
`get_system_prompt()` as a new optional parameter. This lets profile configs
add per-model guidance (e.g. the gemma3:4b "only call a tool when asked"
line) without baking model-specific text into `system_prompt.py`.

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
  "SystemPromptCompact": true,
  "ProviderOverrides": {
    "tool_choice": "auto"
  }
}
```

Note: `SystemPromptCompact: true` is required here because the provider name
is `openai-compatible`, not `ollama`, so the existing fallback hardcode in
4.7 does not auto-enable compact for vLLM-served Gemma.

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

| Feature | Path A — `gemma3:4b` on Ollama (headline) | Path B (vLLM, 12B+) | Path C (Google hosted) |
|---------|--------------------------------------------|---------------------|------------------------|
| Streaming text | ✅ | ✅ | ✅ |
| Tool calling | ⚠️ Reliable at ≤12 exposed tools; degrades to fenced JSON above | ⚠️ Depends on parser config | ✅ Native |
| Parallel tool calls | ❌ Ollama serialises | ⚠️ Parser-dependent (`pythonic` parser supports it) | ✅ |
| Prompt caching | ❌ (Ollama has none) | ⚠️ vLLM prefix cache, server-side, not surfaced | ⚠️ Gemini auto cache may apply |
| System prompt fidelity | ⚠️ Folded into user turn — compact prompt auto-enabled today by provider-hardcode (4.7) | ⚠️ Folded into user turn — set `SystemPromptCompact: true` explicitly | ✅ `system_instruction=` |
| Sub-agents | ❌ Disable — 4B can't reliably spawn | ✅ on 12B+ | ✅ |
| Mode analysis (Stage 1+2) | ❌ Disable | ⚠️ 12B+ only | ✅ |
| Tool search (semantic) | ✅ **Required** — `ToolSearchMaxLoad: 12` caps exposed tools | ⚠️ Needs embedding model | ⚠️ Auto-disabled by `should_activate_tool_search()` for `provider="gemini"`; set `ToolSearchEnabled: "true"` to force on if needed |
| Compaction (summarize) | ⚠️ Quality varies on 4B; consider Haiku sub-agent for compaction | ✅ | ✅ |
| Mutating tools (HITL) | ✅ | ✅ | ✅ |
| Vision (image input) | ✅ gemma3:4b+ | ✅ gemma3:4b+ | ✅ gemma-3-4b-it+ |
| 128K context | ✅ gemma3:4b | ✅ | ✅ |
| Spurious tool-call suppression on chat turns | ⚠️ Requires `SystemPromptExtras` directive (see 4.5) | ✅ | ✅ |

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

**Unknown-tool-name rejection** is **already implemented** — `turn_engine.py:397`
returns `'Error: unknown tool "<name>"'` as a tool_result with `is_error=True`,
fed back to the model on the next turn. The only refinement worth making is
enriching that error message with the available tool names so the model can
self-correct without guessing again. One-line change: replace the existing
content string with `f'Error: unknown tool "{tool_name}". Available tools: '
+ ", ".join(sorted(self._tool_map.keys()))`. Increment a
`gemma_unparsed.hallucinated_name` counter at the same site.

### 6.3 Tool-result message format

All three paths consume the same `{"type": "tool_result", "tool_use_id": ...,
"content": "..."}` user blocks the existing providers convert. No change.

### 6.4 Wire format for `gemma3:4b` on Ollama (Path A, headline target)

This is the empirically observed wire shape Ollama produces when serving
`gemma3:4b` with tools attached. Pinning it down matters because the
4B-scale failure modes are format-level, not semantics-level — when
gemma3:4b "fails" a tool call, it usually emitted *something* tool-shaped
that Ollama silently couldn't parse.

**Chat template.** Gemma 3 uses the standard Gemma turn delimiters:

```
<bos><start_of_turn>user
{system prompt + tool schemas + user message}<end_of_turn>
<start_of_turn>model
{response}<end_of_turn>
```

There is no `system` role. Ollama folds the agent system prompt and the
JSON-Schema tool definitions into the first user turn — this is why
`SystemPromptVariant: "compact"` matters: every byte of unused directive
displaces the actual user question deeper into the prompt.

**Tool-call payload (happy path).** When the model decides to call a tool,
it emits a `<tool_call>` block inside its model turn:

```
<start_of_turn>model
<tool_call>
{"name": "read_file", "arguments": {"path": "src/main.py"}}
</tool_call>
<end_of_turn>
```

Ollama's `/api/chat` (and OpenAI-compatible `/v1/chat/completions`) parses
that block out of the streaming text and surfaces it as:

```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {"function": {"name": "read_file", "arguments": "{\"path\":\"src/main.py\"}"}}
    ]
  }
}
```

`OllamaProvider._parse_chunk()` already converts this to the agent's
internal `tool_use` block shape and synthesises a stable `uuid4()` ID
(same strategy as `GeminiProvider`). **No code change required for the
happy path.**

**Failure modes specific to `gemma3:4b`.** These are the patterns the model
emits when it knows it wants to call a tool but botches the wire shape:

1. **Fenced JSON without the XML wrapper** — at ≥15 exposed tools the model
   tends to emit:
   ```
   ```json
   {"name": "read_file", "arguments": {"path": "src/main.py"}}
   ```
   ```
   Ollama does *not* recognise this as a tool call. It surfaces as plain
   text content; `tool_calls[]` is empty. **Mitigation:** keep the exposed
   tool surface ≤12 via `ToolSearchMaxTools` (see 4.5).
2. **Mixed prose + `<tool_call>`** — the model preambles with explanation
   before the tool-call block, e.g. `"I'll read the file for you. <tool_call>..."`.
   This *does* parse correctly; Ollama emits both content text and
   `tool_calls[]`. `TurnEngine` already handles mixed assistant turns, so
   no change needed — just a quality-of-output observation.
3. **Hallucinated tool names** — the model invokes a tool that isn't in
   the registry. Currently silently fails in the dispatcher. **Mitigation:**
   §6.2's "unknown-tool-name rejection" change in `TurnEngine`, which
   feeds a model-readable error back so it can self-correct.
4. **Over-eager tool calls on conversational turns** — `gemma3:4b` will
   try to call a tool for prompts like "thanks" or "what is 2+2?". The
   12B/27B variants do not exhibit this. **Mitigation:** the
   `SystemPromptExtras` instruction in 4.5 ("Only call a tool when the
   user asks you to perform an action") suppresses ~all of these.
5. **Truncated `<tool_call>` block** — model hits `MaxTokens` mid-JSON. The
   `</tool_call>` close-tag never arrives; Ollama returns the whole thing
   as content text. **Mitigation:** none beyond raising `MaxTokens` to 2048
   (the profile already does this). Log as `gemma_unparsed_tool_call` (4.6)
   so users can see the truncation rate.

**Metric to add (refinement of 4.6).** The `gemma_unparsed_tool_call`
counter should distinguish the four parseable failure shapes so the
operator can tell whether to raise `MaxTokens` (truncation), lower
`ToolSearchMaxTools` (fence-fallback), or switch to the fine-tuned variant
(persistent failures across categories):

| Sub-counter | Triggered when |
|-------------|----------------|
| `gemma_unparsed.fenced_json` | Assistant content contains a fenced JSON block matching `{"name":..., "arguments":...}` |
| `gemma_unparsed.bare_xml` | Assistant content contains `<tool_call>` but no matching `</tool_call>` |
| `gemma_unparsed.hallucinated_name` | Parsed `tool_calls[]` names a tool not in the registry (incremented at `turn_engine.py:397`) |

Categories 1 and 2 are detectable inside `OllamaProvider` from the
assistant message text. Category 3 belongs in `TurnEngine`.

The previously proposed `gemma_unparsed.conversational_attempt` sub-counter
is dropped — it would require an intent-verb taxonomy the codebase does not
have, and it's a low-confidence heuristic. The `SystemPromptExtras` mitigation
in 4.5 is the primary tool against conversational over-eagerness; if that
proves insufficient we add a metric backed by a proper taxonomy.

---

## 7. Config Schema Additions

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `SystemPromptCompact` | `bool \| null` | `null` | Force compact / full system prompt. `null` preserves the current behaviour (`compact=True` iff `provider == "ollama"`, see `bootstrap.py:208`); `true` forces compact (needed for non-Ollama Gemma paths); `false` forces full |
| `SystemPromptExtras` | `list[str]` | `[]` | Append model-specific guidance lines (e.g. gemma3:4b "only call a tool when asked to act") after the core directives, without baking model-specific text into `system_prompt.py` |
| `ProviderOverrides` | `dict[str, Any]` | `{}` | Forward server-specific kwargs (e.g. `tool_choice`) — already proposed by PLAN-local-model-ecosystems Phase 3 |

`ToolSearchMaxLoad` is **not** new — the existing `tool_search_max_load`
field (`agent_config.py:149`) already caps the number of tools bound per
turn. Setting it to 12 in the gemma3 profile is sufficient.

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
| `config-base.json` | 1 | Pricing zero entries for `gemini/gemma-3-*-it`, `ollama/gemma3:*`, and `ollama/orieg/gemma3-tools:4b-ft` |
| `src/micro_x_agent_loop/constants.py` | 1 | `TOOL_SEARCH_CONTEXT_WINDOWS` additions: `"gemma3"` and `"gemma-3-*-it"` entries (controls tool-search activation thresholds, **not** compaction) |
| `src/micro_x_agent_loop/agent_config.py` | 2 | `system_prompt_compact: bool \| None = None`, `system_prompt_extras: list[str] = []` fields |
| `src/micro_x_agent_loop/app_config.py` | 2 | Parse `SystemPromptCompact` and `SystemPromptExtras` from config |
| `src/micro_x_agent_loop/system_prompt.py` | 2 | Append `SystemPromptExtras` lines to rendered prompt (the existing `compact` parameter already handles directive trimming) |
| `src/micro_x_agent_loop/bootstrap.py` | 2 | Replace hardcoded `compact=app.provider_name == "ollama"` (line 208) with explicit-config-or-fallback; thread `SystemPromptExtras` |
| `src/micro_x_agent_loop/server/agent_manager.py` | 2 | Same `compact=` change as bootstrap.py (line 154) |
| `src/micro_x_agent_loop/providers/ollama_provider.py` | 2 | Log `gemma_unparsed.fenced_json` / `gemma_unparsed.bare_xml` metrics when assistant content matches those shapes but `tool_calls[]` is empty (requires a post-stream hook — see §4.6) |
| `src/micro_x_agent_loop/turn_engine.py` | 2 | Enrich existing unknown-tool error at line 397 with available-tool list; increment `gemma_unparsed.hallucinated_name` counter |
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
| `test_pricing_entries_complete` | 1 | All Gemma model IDs in profile configs resolve to a pricing entry (gemini/* and ollama/*) |
| `test_tool_search_context_window_lookup` | 1 | `_get_context_window("gemma3:4b")` returns 128_000; `_get_context_window("gemma-3-4b-it")` returns 128_000 |
| `test_system_prompt_compact_explicit_config` | 2 | `SystemPromptCompact: true` produces compact prompt regardless of provider; `SystemPromptCompact: false` produces full prompt even for ollama provider; `null` preserves the legacy `provider == "ollama"` fallback |
| `test_system_prompt_extras_appended` | 2 | `SystemPromptExtras` lines appear in the rendered prompt after the core directives |
| `test_tool_search_max_load_caps_bound_tools` | 2 | `ToolSearchMaxLoad: 12` binds at most 12 tools per turn (verifies the existing field, not a new one) |
| `test_turn_engine_unknown_tool_lists_available` | 2 | Unknown tool name → tool_result error message *includes the available tool names*; `gemma_unparsed.hallucinated_name` increments |
| `test_ollama_detects_fenced_json_tool_call` | 2 | Assistant text containing a fenced `{"name":..., "arguments":...}` block without parsed `tool_calls[]` increments `gemma_unparsed.fenced_json` |
| `test_ollama_detects_truncated_tool_call_xml` | 2 | Assistant text containing an unclosed `<tool_call>` increments `gemma_unparsed.bare_xml` |
| `test_gemma3_4b_happy_path_tool_call` | 2 | `FakeStreamProvider` emitting the canonical `<tool_call>{"name":..., "arguments":{...}}</tool_call>` shape → `TurnEngine` dispatches the named tool with parsed args (uses provider fake; no live Ollama needed) |
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
            - SystemPromptCompact: expose existing compact prompt as explicit config (decouple from provider hardcode)
            - SystemPromptExtras: new list[str] appended to system prompt
            - Enrich existing unknown-tool error at turn_engine.py:397 with available-tool list; add hallucinated_name counter
            - Add fenced_json / bare_xml unparsed tool-call metrics in OllamaProvider
            - config-standard-ollama-gemma3.json profile (reuses existing ToolSearchMaxLoad)
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
| What is the actual tool-call success rate of `gemma3:4b` on Ollama at the proposed `ToolSearchMaxLoad=12` cap? | Phase 2 | Run the eval harness from PLAN-behavioural-eval-suite once it exists. Gate criterion: ≥80% on the canonical tool-use prompts. If below, fall back to `orieg/gemma3-tools:4b-ft` |
| Is `ToolSearchMaxLoad=12` the right ceiling, or does the boundary sit at 10 / 15? | Phase 2 | Sweep the cap from 8 → 20 against a fixed prompt set; record `gemma_unparsed.fenced_json` rate. Ship Phase 2 profile as "preliminary" until this sweep completes |
| Does the `SystemPromptExtras` "only call a tool when asked" instruction generalise, or is it gemma3:4b-specific? | Phase 2 | If generic, move it into a new `_TOOL_USE_DIRECTIVE`; if model-specific, leave in profile config |
| Does Gemini auto-cache fire for Gemma model IDs, or only Gemini-branded ones? | Phase 1 metrics review | Check `usage_metadata.cached_content_token_count` on hosted Gemma turns |
| For Path C (Gemma via `provider="gemini"`), should `should_activate_tool_search()` continue to auto-disable tool search? | Phase 1 | The cache-preserving heuristic exists because Gemini gives a 90% cache read discount; whether that discount applies to *Gemma* model IDs on the same endpoint is unknown. Default to explicit `ToolSearchEnabled: "true"` in the Path C profile until measured |
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
