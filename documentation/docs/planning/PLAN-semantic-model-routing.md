# Plan: Semantic Model Routing Across Providers

## Status

**Completed** — All 4 phases implemented 2026-03-21.

## Problem

The current per-turn routing (`turn_classifier.py`) uses simple heuristics (message length, turn iteration, keyword blocklist) to decide "main model" vs "cheap model" — both served by the **same provider**. This leaves significant cost and quality optimisation on the table:

1. **No task-type awareness** — A code review, a translation, and a factual lookup all route the same way despite having very different model-quality requirements.
2. **Single provider per routing slot** — Cannot route to Ollama for trivial tasks, OpenAI for code, and Anthropic for complex reasoning within the same session.
3. **No quality/cost/latency trade-off** — The classifier doesn't consider model pricing, latency, or availability — only a binary cheap/main decision.
4. **No learning** — Routing decisions are static rules with no feedback from actual outcomes (cost, quality, user satisfaction).

## Goals

- Route each LLM call to the **best-fit model across all configured providers** based on task semantics, cost, and quality requirements.
- Maintain prompt-cache efficiency (avoid cache invalidation from provider switching).
- Keep routing latency negligible (< 50ms overhead per turn).
- Preserve the existing opt-in, composable config pattern (ADR-012).
- Enable measurable cost savings via metrics (prerequisite: cost metrics logging — already complete).

## Non-Goals

- Building a standalone gateway/proxy service (superseded by existing architecture).
- Training custom routing models (use off-the-shelf classification).
- Real-time model benchmarking or A/B testing infrastructure.

---

## Architecture

### Core Concept: Router → Provider Pool

```
User message
    ↓
┌──────────────────────────┐
│   Semantic Router        │
│  ┌────────────────────┐  │
│  │ 1. Rule Engine     │  │  ← Existing heuristics (turn_classifier.py) — fast path
│  │ 2. Embedding        │  │  ← Task-type classification via embeddings (no LLM call)
│  │    Classifier       │  │
│  │ 3. LLM Classifier  │  │  ← Fallback: tiny LLM classifies ambiguous tasks
│  └────────────────────┘  │
│           ↓               │
│   RoutingDecision         │
│   (provider, model,       │
│    confidence, reason)    │
└──────────────────────────┘
    ↓
┌──────────────────────────┐
│   Provider Pool           │
│  ┌──────────┐ ┌────────┐ │
│  │Anthropic │ │ OpenAI │ │
│  │(Sonnet/  │ │(GPT-4o/│ │
│  │ Opus/    │ │ mini)  │ │
│  │ Haiku)   │ │        │ │
│  └──────────┘ └────────┘ │
│  ┌──────────┐ ┌────────┐ │
│  │ Ollama   │ │DeepSeek│ │
│  │(local)   │ │        │ │
│  └──────────┘ └────────┘ │
└──────────────────────────┘
    ↓
TurnEngine.stream_chat(effective_provider, effective_model, ...)
```

### Key Design Decisions

**D1: Three-stage classifier (rule → embedding → LLM)**
- Stage 1 (rules) handles obvious cases with zero latency — preserves current `turn_classifier.py` behaviour.
- Stage 2 (embedding) classifies task type using a lightweight local embedding model or pre-computed centroids. ~5ms overhead.
- Stage 3 (LLM) is a fallback for ambiguous cases only — uses the cheapest available model (Haiku/GPT-4o-mini). ~200ms but rare.

**D2: Provider Pool replaces single provider**
- `TurnEngine` currently takes one `provider` + optional `routing_model`. Replace with a `ProviderPool` that holds multiple initialised providers.
- Each provider is tagged with capabilities, cost tier, and availability.
- The router returns a `(provider_name, model_name)` tuple, and the pool dispatches.

**D3: Task taxonomy**
Define a fixed set of task types that map to routing policies:

| Task Type | Description | Default Route | Rationale |
|-----------|-------------|---------------|-----------|
| `trivial` | Greetings, acknowledgements, yes/no | Cheapest available (Ollama/Haiku) | No reasoning needed |
| `conversational` | Short Q&A, clarifications | Cheap (Haiku/GPT-4o-mini) | Light reasoning |
| `factual_lookup` | Simple factual questions | Cheap (Haiku/GPT-4o-mini) | Recall, not reasoning |
| `summarization` | Summarise text/results | Cheap (Haiku/GPT-4o-mini) | Existing compaction pattern |
| `code_generation` | Write/edit code | Main (Sonnet/GPT-4o) | Quality-sensitive |
| `code_review` | Review/explain code | Main (Sonnet/GPT-4o) | Reasoning required |
| `analysis` | Complex reasoning, planning, design | Best available (Opus/Sonnet) | Quality-critical |
| `tool_continuation` | Processing tool results | Cheap → Main (adaptive) | Depends on result complexity |
| `creative` | Writing, brainstorming | Main (Sonnet/GPT-4o) | Quality-sensitive |

**D4: Routing policy is config-driven**
Routing policies live in `config.json` under a new `SemanticRouting` key, not hardcoded:

```json
{
  "SemanticRoutingEnabled": false,
  "SemanticRoutingStrategy": "rules+embeddings",
  "RoutingPolicies": {
    "trivial":           { "provider": "ollama", "model": "llama3:8b" },
    "conversational":    { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "factual_lookup":    { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "summarization":     { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "code_generation":   { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
    "code_review":       { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
    "analysis":          { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
    "tool_continuation": { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "creative":          { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" }
  },
  "RoutingFallback": { "provider": "#Provider", "model": "#Model" }
}
```

**D5: Cache-awareness**
- Track which provider currently holds a warm cache for this session.
- Add a configurable `cache_switch_penalty` cost (estimated cache-rebuild cost in tokens).
- Router factors in the penalty when considering a cross-provider switch: only switch if expected savings exceed the cache rebuild cost.
- Within the same provider, model switches preserve cache (Anthropic caches are per-org, not per-model).

**D6: Fallback and availability**
- If a provider is unavailable (connection error, rate limit), the pool marks it temporarily unavailable and re-routes to the next best option.
- Ollama availability checked at startup (health endpoint).
- Provider errors trigger fallback, not failure.

---

## Phases

### Phase 1: Provider Pool & Multi-Provider Dispatch

**Goal:** Enable routing to different providers within a single session.

**Changes:**

| File | Change |
|------|--------|
| `provider_pool.py` (new) | `ProviderPool` class: holds `dict[str, LLMProvider]`, dispatches by provider name. Health checks, availability tracking. |
| `agent_config.py` | Add `SemanticRoutingEnabled`, `RoutingPolicies`, `RoutingFallback` config fields. Add `additional_providers` list for pool initialisation. |
| `config-base.json` | Add `SemanticRoutingEnabled: false` and default `RoutingPolicies`. |
| `bootstrap.py` | Initialise `ProviderPool` with all configured providers. Pass pool to `TurnEngine`. |
| `turn_engine.py` | Accept `ProviderPool` (optional, backwards-compatible). When pool is present, dispatch to `pool.stream_chat(provider, model, ...)` instead of `self._provider.stream_chat(model, ...)`. |
| `app_config.py` | Parse new config keys, resolve `#Provider`/`#Model` self-references in routing policies. |

**Acceptance criteria:**
- Config can define multiple providers with separate API keys.
- `TurnEngine` can dispatch a single turn to a different provider than the main one.
- Existing single-provider behaviour unchanged when `SemanticRoutingEnabled=false`.
- Unit tests for `ProviderPool` dispatch, fallback, availability.

### Phase 2: Semantic Task Classifier

**Goal:** Classify each turn into a task type using a three-stage pipeline.

**Changes:**

| File | Change |
|------|--------|
| `semantic_classifier.py` (new) | Three-stage classifier: rules → embeddings → LLM fallback. Returns `TaskClassification(task_type, confidence, stage_used, reason)`. |
| `turn_classifier.py` | Refactor: extract rule-matching into reusable functions. `classify_turn()` becomes Stage 1 of the semantic classifier. |
| `task_taxonomy.py` (new) | `TaskType` enum with the 9 types. Mapping from `TaskType` → routing policy key. |
| `agent_config.py` | Add `SemanticRoutingStrategy` config (`"rules"`, `"rules+embeddings"`, `"rules+embeddings+llm"`). Embedding model config. |
| `config-base.json` | `SemanticRoutingStrategy: "rules+embeddings"`. |

**Stage 1 — Rule engine (< 1ms):**
- Reuse existing `turn_classifier.py` heuristics.
- Add new rules: greeting patterns → `trivial`, `summarize/summarise` → `summarization`, code fences or file paths → `code_generation`.
- If confidence > 0.9, return immediately.

**Stage 2 — Embedding classifier (~5ms):**
- Use a small local embedding model (e.g., `all-MiniLM-L6-v2` via `sentence-transformers`, or Ollama embeddings).
- Pre-compute centroid embeddings for each task type from labelled examples.
- Classify by cosine similarity to nearest centroid.
- If confidence > 0.8, return.

**Stage 3 — LLM classifier (~200ms, rare):**
- Send a minimal classification prompt to the cheapest available model.
- Structured output: `{"task_type": "...", "confidence": 0.0-1.0}`.
- Used only when stages 1+2 are both low-confidence (expected < 5% of turns).

**Acceptance criteria:**
- Classifier correctly categorises a test suite of 50+ labelled prompts.
- Stage 2 adds < 10ms latency.
- Stage 3 invoked < 5% of turns on representative workloads.
- Unit tests for each stage independently + integrated pipeline.

### Phase 3: Routing Integration & Cache-Aware Dispatch

**Goal:** Wire the semantic classifier into the turn engine with cache-aware routing.

**Changes:**

| File | Change |
|------|--------|
| `turn_engine.py` | Replace binary `turn_classifier` with `semantic_classifier`. Use `ProviderPool` for dispatch. Track active-cache provider. Apply cache-switch penalty logic. |
| `provider_pool.py` | Add `active_cache_provider` tracking. `estimate_cache_penalty(from_provider, to_provider)` method. |
| `metrics.py` | Extend `SessionAccumulator` to track per-task-type cost breakdown. New fields: `task_type`, `routing_stage` on API call records. |
| `usage.py` | Add `task_type` and `routing_stage` fields to `UsageResult`. |
| `commands/cost.py` | Extend `/cost` to show per-task-type and per-provider breakdown. |

**Cache-switch decision logic:**
```python
if best_route.provider != active_cache_provider:
    switch_cost = estimate_cache_rebuild_tokens(session) * input_price_per_token
    expected_savings = (main_model_cost - cheap_model_cost) * estimated_output_tokens
    if expected_savings <= switch_cost * cache_switch_threshold:
        # Stay with current provider — cache is more valuable
        route = fallback_to_current_provider(best_route.task_type)
```

**Acceptance criteria:**
- Routing decisions visible in `/cost` output per task type.
- Cache-aware logic prevents unnecessary provider switching on short tasks.
- Metrics capture routing stage, task type, and provider per API call.
- Integration tests covering: rule-only routing, embedding routing, cache-penalty override.

### Phase 4: Feedback Loop & Adaptive Routing

**Goal:** Use historical cost/quality data to refine routing policies over time.

**Changes:**

| File | Change |
|------|--------|
| `routing_feedback.py` (new) | Collects per-turn outcomes: cost, latency, user satisfaction signals (explicit feedback, retries, follow-up corrections). Stores in SQLite. |
| `semantic_classifier.py` | Add optional `historical_accuracy` input — adjusts confidence thresholds per task type based on observed error rates. |
| `memory/schema.py` | New table: `routing_outcomes` (session_id, turn, task_type, provider, model, cost, latency_ms, quality_signal, timestamp). |
| `commands/routing.py` (new) | `/routing` command: show routing stats, per-task-type accuracy, cost savings achieved. |

**Quality signals:**
- **Positive:** User continues conversation (implicit satisfaction), no immediate retry.
- **Negative:** User immediately re-asks the same question, user says "no" / "that's wrong", turn produces an error.
- **Explicit:** Future `/feedback` command or thumbs-up/down integration.

**Adaptive behaviour:**
- If a task type consistently gets re-routed to main after cheap fails, auto-promote it.
- If a provider shows high error rates, demote it in the pool.
- Weekly summary of routing efficiency stored as a routing config suggestion.

**Acceptance criteria:**
- Routing outcomes persisted to SQLite.
- `/routing` command shows accuracy and savings metrics.
- Adaptive threshold adjustment demonstrated on synthetic workload.
- No regressions on existing test suite.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Embedding model adds dependency | Increases install size (~100MB) | Make embeddings optional; `"rules"` strategy works without them |
| Cross-provider message format incompatibility | Tool schemas / message history may not transfer cleanly | Providers already normalise to internal format; pool dispatches through the same `LLMProvider` interface |
| Cache invalidation from frequent switching | Negates prompt-caching savings | Cache-switch penalty logic (Phase 3); default to same-provider when savings are marginal |
| Misclassification routes complex task to weak model | Poor output quality | Complexity-keyword guard preserved from current classifier; confidence thresholds; user can override via config |
| Ollama availability | Local model may not be running | Health check at startup; graceful fallback to cloud providers |
| Added latency from classification | Slows down response time | Stage 1 is < 1ms; Stage 2 < 10ms; Stage 3 rare (< 5% of turns) |

## Dependencies

- **Cost Metrics Logging** (complete) — required for measuring routing ROI.
- **Multi-Provider Support** (complete) — Gemini + DeepSeek providers already exist.
- **Per-Turn Routing** (complete) — Phase 1 refactors this into the semantic classifier.
- **Externalise Pricing Data** (complete) — pricing in config enables cost-aware routing math.
- **sentence-transformers** (new dependency, Phase 2 only) — or Ollama embeddings as alternative.

## Success Metrics

| Metric | Target |
|--------|--------|
| Cost reduction vs current routing | > 30% on mixed workloads |
| Routing overhead latency | < 50ms p99 |
| Misclassification rate | < 5% (validated against labelled test set) |
| Cache-hit preservation | No degradation vs single-provider baseline |
| Phase 1 delivery | Config + pool + dispatch working, no new dependencies |

**Post-implementation review:** See [PLAN-routing-simplification.md](PLAN-routing-simplification.md) — Appendix: Code-Level Critical Review.
