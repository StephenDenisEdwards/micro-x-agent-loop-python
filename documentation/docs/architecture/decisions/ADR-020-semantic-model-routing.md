# ADR-020: Semantic Model Routing Across Providers

## Status

Accepted — 2026-03-21

Extends [ADR-012](ADR-012-layered-cost-reduction.md) (layered cost reduction) as a sixth cost reduction layer.

## Context

ADR-012 established five independent cost reduction layers. Phase 3b added per-turn model routing — a binary classifier that routes simple turns to a cheaper model based on heuristics (message length, turn iteration, keyword blocklist). This delivered measurable savings but left two significant opportunities:

1. **No task-type awareness.** The heuristic classifier cannot distinguish a code review from a factual question — it only knows whether the message is short, whether tools are present, and whether it's a tool-result continuation. Two messages of identical length may have very different model-quality requirements.

2. **Single-provider constraint.** Per-turn routing selects between two models on the *same* provider. This prevents routing trivial tasks to free local models (Ollama) while keeping complex reasoning on Anthropic — a combination that could reduce costs to near-zero for ~40% of turns.

Options considered:

1. **Extend the heuristic classifier with more rules.** Low effort but poor accuracy for ambiguous messages. Rules don't compose well at scale — each new rule interacts with all existing rules.

2. **Use an embedding model for classification.** High accuracy but adds a ~100MB dependency (`sentence-transformers`) and inference latency. Overkill for a 9-class taxonomy where keyword signals are strong.

3. **Three-stage classifier (rules → keywords → LLM) with a provider pool.** Rules handle obvious cases (zero latency), keyword-vector similarity handles the middle ground (< 1ms, no external deps), and a cheap LLM classifies rare ambiguous cases. Combined with a multi-provider dispatch pool.

## Decision

Adopt option 3: a three-stage semantic classifier with a provider pool, config-driven routing policies, and an outcome feedback loop.

Reasons:

- **Layered classification matches signal quality.** Most turns (estimated 60-70%) are clearly classifiable by rules alone. The keyword stage catches another 25-30%. The LLM stage fires < 5% of the time. This means < 1ms overhead for 95%+ of turns.

- **No new external dependencies.** The keyword-vector stage uses pre-defined keyword centroids and cosine similarity — pure Python, no ML libraries. The LLM stage uses the existing provider infrastructure.

- **Provider pool is a natural extension.** The existing `create_provider()` factory already supports 5 providers (Anthropic, OpenAI, DeepSeek, Gemini, Ollama). The pool holds multiple instances and dispatches by name — a thin coordination layer, not a new abstraction.

- **Config-driven policies match ADR-012 pattern.** Each task type maps to a (provider, model) pair in `config.json`. Self-references (`#Provider`, `#Model`) mean the default config routes everything through the main provider — zero behaviour change until the user explicitly configures cross-provider routing.

- **Feedback loop enables adaptive routing.** SQLite-backed outcome recording tracks cost, latency, and quality signals per task type. Adaptive thresholds prevent the system from repeatedly routing complex tasks to cheap models when quality degrades.

### Architecture Components

**1. Task Taxonomy** — 9 fixed task types (`trivial`, `conversational`, `factual_lookup`, `summarization`, `code_generation`, `code_review`, `analysis`, `tool_continuation`, `creative`). Each task type is either "cheap-eligible" or "main-required". The taxonomy is extensible but changes require updating the classifier and config schema.

**2. Semantic Classifier** — Three-stage pipeline:
- Stage 1 (rules): regex patterns + turn context signals. Subsumes the existing `turn_classifier.py` heuristics.
- Stage 2 (keywords): cosine similarity between tokenized message and pre-defined keyword centroids per task type.
- Stage 3 (LLM): cheapest available model classifies ambiguous prompts via structured JSON output.

**3. Provider Pool** — Dict of named `LLMProvider` instances with health tracking (exponential-backoff cooldown) and cache-aware switching (penalty-based decision to prevent cache invalidation from frequent provider switches).

**4. Routing Feedback** — SQLite table `routing_outcomes` with per-turn records. Provides aggregate stats (per task type, provider, classification stage) and adaptive confidence thresholds.

### Relationship to Per-Turn Routing

Semantic routing **supersedes** per-turn routing when both are enabled. The semantic classifier produces the same outputs for the cases that per-turn routing handles (tool-result continuations, complexity guard) plus task-type classification for all other cases. The legacy `PerTurnRoutingEnabled` path remains functional for users who prefer the simpler binary classifier.

## Consequences

**Easier:**

- Reducing session cost by 30-50% beyond what per-turn routing achieves, by routing ~40% of turns to Haiku or free local models
- Observing routing decisions via structured logging and the `/routing` command
- Configuring per-task-type provider/model mapping without code changes
- Adding Ollama-based local inference for trivial tasks at zero API cost
- Debugging routing decisions via the stage/confidence/reason chain

**Harder:**

- Understanding the three-stage classification pipeline when debugging unexpected routing. Mitigated by: structured logging with stage, confidence, and reason on every turn.
- Configuration surface area increases by 7 new fields. Mitigated by: sensible defaults that produce no behaviour change until explicitly enabled.
- Provider pool adds complexity to error handling — a call may fail on one provider and succeed on the fallback. Mitigated by: health tracking with exponential backoff and structured fallback logging.

**Risks:**

- **Misclassification routes complex task to weak model.** A factual-looking question that actually requires deep reasoning could route to Haiku. Mitigated by: complexity keyword guard (checked first, overrides all cheap routing), confidence thresholds, user-configurable policies, adaptive thresholds from feedback.
- **Cross-provider cache invalidation.** Switching providers on adjacent turns loses the prompt prefix cache on the original provider. Mitigated by: cache-switch penalty logic in the provider pool, defaulting to same-provider routing in the base config.
- **Keyword-vector accuracy.** Pre-defined centroids may not match all user vocabularies. Mitigated by: rules handle the highest-confidence cases before keywords are consulted; the LLM fallback catches edge cases; the feedback loop auto-adjusts thresholds.

**Related:**

- [ADR-012](ADR-012-layered-cost-reduction.md) — this extends the layered cost reduction architecture as a sixth layer
- [DESIGN-cache-preserving-tool-routing.md](../design/DESIGN-cache-preserving-tool-routing.md) — cache-awareness principles applied to the provider pool's switching logic
- [PLAN-semantic-model-routing.md](../planning/PLAN-semantic-model-routing.md) — original plan with phase breakdown
