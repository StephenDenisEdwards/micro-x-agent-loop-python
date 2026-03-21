# Design: Semantic Model Routing Across Providers

## Status

**Completed** — all 4 phases implemented 2026-03-21.

## Problem

The existing per-turn routing (`turn_classifier.py`) uses simple heuristics (message length, turn iteration, keyword blocklist) to decide between a "main" and "cheap" model — both served by the same provider. This leaves cost optimisation on the table:

1. **No task-type awareness.** A code review, a translation, and a factual lookup all route the same way despite having very different quality requirements.
2. **Single provider per routing slot.** Cannot route trivial tasks to a free local model (Ollama) while keeping complex reasoning on Anthropic.
3. **No cost/quality trade-off math.** The classifier doesn't consider pricing, latency, or cache state — just binary cheap/main.
4. **No learning.** Routing decisions are static rules with no feedback from outcomes.

## Solution

A four-component architecture layered on top of the existing agent loop:

```
User message
    ↓
┌─────────────────────────────────┐
│  Semantic Classifier             │
│  Stage 1: Rules      (< 1ms)    │ ← Extended turn_classifier heuristics
│  Stage 2: Keywords   (< 1ms)    │ ← Cosine similarity to task-type centroids
│  Stage 3: LLM        (~200ms)   │ ← Cheapest model classifies ambiguous tasks
│           ↓                      │
│  TaskClassification              │
│  (task_type, confidence, stage)  │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  Routing Policies (config.json)  │
│  task_type → (provider, model)   │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  Provider Pool                   │
│  {anthropic, openai, ollama, …}  │
│  • Health tracking               │
│  • Fallback on error             │
│  • Cache-switch penalty          │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  Routing Feedback Store          │
│  SQLite: routing_outcomes        │
│  • Per-task-type stats           │
│  • Adaptive thresholds           │
│  • /routing command              │
└─────────────────────────────────┘
```

## Task Taxonomy

Nine fixed task types, each with distinct quality/cost profiles:

| Task Type | Description | Default Route | Rationale |
|-----------|-------------|---------------|-----------|
| `trivial` | Greetings, yes/no | Cheapest (Haiku/Ollama) | No reasoning needed |
| `conversational` | Short Q&A | Cheap (Haiku) | Light reasoning |
| `factual_lookup` | Simple factual questions | Cheap (Haiku) | Recall, not reasoning |
| `summarization` | Summarise text/results | Cheap (Haiku) | Pattern from compaction |
| `code_generation` | Write/edit code | Main (Sonnet) | Quality-sensitive |
| `code_review` | Review/explain code | Main (Sonnet) | Reasoning required |
| `analysis` | Complex reasoning, design | Main (Sonnet) | Quality-critical |
| `tool_continuation` | Processing tool results | Cheap (Haiku) | Pattern from per-turn routing |
| `creative` | Writing, brainstorming | Main (Sonnet) | Quality-sensitive |

Defined in `task_taxonomy.py` as a `TaskType` string enum with `CHEAP_TASK_TYPES` and `MAIN_TASK_TYPES` frozen sets.

## Semantic Classifier

`semantic_classifier.py` — three-stage pipeline, all sync (no async, no state).

### Stage 1: Rules (< 1ms)

Extends the existing `turn_classifier.py` heuristics with task-type-specific patterns:

| Rule | Pattern | Task Type | Confidence |
|------|---------|-----------|------------|
| Tool continuation | `turn_iteration > 0` | `tool_continuation` | 0.95 |
| Complexity guard | Keywords: design, architect, analyze… | `analysis` | 0.85 |
| Greeting | `^(hi|hello|thanks|ok|…)` on short messages | `trivial` | 0.95 |
| Summarization | `\b(summarize|tldr|recap|…)\b` | `summarization` | 0.90 |
| Code generation | `\b(write|create|implement)\b.*\b(function|class|…)\b` | `code_generation` | 0.85 |
| Code review | `\b(review|explain|debug)\b.*\b(code|function|…)\b` | `code_review` | 0.85 |
| Analysis | `\b(design|architect|compare|…)\b` | `analysis` | 0.85 |
| Factual | `\b(what is|who is|define|…)\b` | `factual_lookup` | 0.80 |
| Creative | `\b(draft|compose|brainstorm|…)\b` | `creative` | 0.75 |

Returns `None` if no rule matches with sufficient confidence → falls through to Stage 2.

### Stage 2: Keywords (< 1ms)

Keyword-vector cosine similarity. Pre-defined keyword vectors per task type act as centroids in a lightweight "embedding space". No external dependencies.

**Mechanism:**
1. Tokenize the user message (lowercase, `[a-z]+` regex).
2. For each task type, compute cosine similarity between the token bag and the keyword vector.
3. Highest-scoring task type wins.
4. Confidence mapped from raw cosine score: `min(0.85, 0.4 + score * 0.6)`.

### Stage 3: LLM (async, ~200ms, rare)

For ambiguous messages where neither Stage 1 nor Stage 2 produces sufficient confidence. Sends a minimal classification prompt to the cheapest available model, requesting a JSON response:

```json
{"task_type": "<type>", "confidence": 0.0-1.0}
```

**Design choice:** Stage 3 is parse-only in the sync pipeline (`parse_stage3_response` + `build_stage3_prompt`). The async LLM call is the caller's responsibility. The `classify_task()` entry point runs Stages 1–2 synchronously and returns the best result; the caller can check confidence and invoke Stage 3 separately if needed.

### Pipeline Configuration

`SemanticRoutingStrategy` controls depth:
- `"rules"` — Stage 1 only (zero overhead, lowest accuracy)
- `"rules+keywords"` — Stages 1–2 (default, < 1ms overhead)
- `"rules+keywords+llm"` — All three (Stage 3 invoked by caller for low-confidence results)

## Provider Pool

`provider_pool.py` — manages multiple `LLMProvider` instances.

### Initialisation

At agent startup, the pool is populated from `RoutingPolicies`:
1. The main provider is always included.
2. For each unique provider name in routing policies, a new `LLMProvider` instance is created via `create_provider()`.
3. API keys are resolved per provider via `resolve_runtime_env()`.

### Dispatch

`pool.stream_chat(RoutingTarget, ...)` dispatches to the named provider:
1. Check if target provider is available (health status).
2. If unavailable, fall back to `RoutingFallbackProvider`.
3. If fallback also unavailable, try any available provider.
4. If none available, raise `ValueError`.

### Health Tracking

`ProviderStatus` per provider:
- `available: bool` — toggled by success/error.
- `consecutive_errors: int` — tracks error streaks.
- `cooldown_until: float` — exponential backoff (5s base, 60s max).
- Auto-recovery: `is_available()` checks if cooldown has expired.

### Cache-Aware Switching

The pool tracks which provider currently holds a warm prefix cache (`active_cache_provider`). `should_switch_provider()` evaluates whether expected savings justify the cache rebuild cost:

```python
if savings_cost > penalty_cost:
    switch_providers()
else:
    stay_with_current_provider()
```

Configurable via `cache_switch_penalty_tokens`.

## Routing Feedback

`routing_feedback.py` — SQLite-backed outcome recording.

### Schema

```sql
CREATE TABLE routing_outcomes (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    turn_number INTEGER,
    task_type TEXT,       -- "trivial", "code_generation", etc.
    provider TEXT,        -- "anthropic", "ollama", etc.
    model TEXT,
    cost_usd REAL,
    latency_ms REAL,
    stage TEXT,           -- "rules", "keywords", "llm"
    confidence REAL,
    quality_signal INTEGER,  -- -1, 0, +1
    timestamp REAL
);
```

### Adaptive Thresholds

`get_adaptive_thresholds()` computes per-task-type confidence thresholds from the last 7 days of data. If a task type consistently receives negative quality signals, its threshold is raised — requiring higher confidence before routing cheaply.

Formula: `threshold = min(0.95, 0.6 + error_rate * 0.5)`

### `/routing` Command

Five views:
- `/routing` — summary (total calls, cost, task types, stage percentages, adaptive thresholds)
- `/routing tasks` — per-task-type table (count, avg cost, avg latency, avg confidence, quality signals)
- `/routing providers` — per-provider table (count, avg cost, avg latency, errors, total cost)
- `/routing stages` — classification stage breakdown (rules vs keywords vs LLM)
- `/routing recent` — last 20 routing decisions with full details

## Configuration

All configuration in `config.json` under existing patterns (ADR-012):

```json
{
  "SemanticRoutingEnabled": false,
  "SemanticRoutingStrategy": "rules+keywords",
  "RoutingPolicies": {
    "trivial":           { "provider": "#Provider", "model": "claude-haiku-4-5-20251001" },
    "conversational":    { "provider": "#Provider", "model": "claude-haiku-4-5-20251001" },
    "factual_lookup":    { "provider": "#Provider", "model": "claude-haiku-4-5-20251001" },
    "summarization":     { "provider": "#Provider", "model": "claude-haiku-4-5-20251001" },
    "code_generation":   { "provider": "#Provider", "model": "#Model" },
    "code_review":       { "provider": "#Provider", "model": "#Model" },
    "analysis":          { "provider": "#Provider", "model": "#Model" },
    "tool_continuation": { "provider": "#Provider", "model": "claude-haiku-4-5-20251001" },
    "creative":          { "provider": "#Provider", "model": "#Model" }
  },
  "RoutingFallbackProvider": "#Provider",
  "RoutingFallbackModel": "#Model",
  "RoutingFeedbackEnabled": false,
  "RoutingFeedbackDbPath": ".micro_x/routing.db"
}
```

`#Provider` and `#Model` self-references are resolved by the config system (existing `_expand_config_refs`). This means the default policies route cheap tasks to Haiku on the same provider and complex tasks to the main model — zero cross-provider switching until the user explicitly configures different providers.

## Integration Points

### TurnEngine

The routing decision happens in `TurnEngine.run()` at the same point where legacy per-turn routing was:

1. If `semantic_classifier` is set, call it with the user message context.
2. Map the `TaskClassification.task_type` to a `RoutingTarget` via `_resolve_routing_target()`.
3. If a `ProviderPool` is set, dispatch via `pool.stream_chat(target, ...)`.
4. Otherwise, dispatch via `self._provider.stream_chat(model, ...)` (legacy path).
5. Record `call_type` as `semantic:<task_type>` for metrics.

### Agent

`Agent.__init__()` builds the provider pool and classifier when `SemanticRoutingEnabled=true`:
- Creates `ProviderPool` with all providers referenced in routing policies.
- Creates a `partial(classify_task, ...)` with configured complexity keywords and strategy.
- If `RoutingFeedbackEnabled`, creates a `RoutingFeedbackStore` and wires a callback.
- Semantic routing supersedes per-turn routing when both are configured.

### Backward Compatibility

- `SemanticRoutingEnabled` defaults to `false` — no change in behaviour.
- Legacy `PerTurnRoutingEnabled` continues to work as before.
- When both are enabled, semantic routing takes precedence.
- All existing tests pass without modification (except adding `on_routing` to `CommandRouter` test fixture).

## File Inventory

| File | Type | Purpose |
|------|------|---------|
| `task_taxonomy.py` | New | `TaskType` enum, cost tier sets |
| `semantic_classifier.py` | New | Three-stage classifier pipeline |
| `provider_pool.py` | New | Multi-provider dispatch, health, cache |
| `routing_feedback.py` | New | SQLite outcome store, adaptive thresholds |
| `agent_config.py` | Modified | +7 config fields |
| `app_config.py` | Modified | Parse new config keys |
| `config-base.json` | Modified | Default routing policies |
| `turn_engine.py` | Modified | Semantic dispatch, `_resolve_routing_target()` |
| `agent.py` | Modified | Pool + classifier + feedback wiring |
| `bootstrap.py` | Modified | Pass routing config to AgentConfig |
| `commands/router.py` | Modified | `/routing` command routing |
| `commands/command_handler.py` | Modified | `/routing` implementation |
