# Manual Test Plan — QW-1: Stage2Model → Haiku

**Related review:** [cost-reduction-review.md](../review/cost-reduction-review.md) — Strategy 8 (Per-Turn Model Routing)
**Code under test:** `src/micro_x_agent_loop/mode_selector.py`; `src/micro_x_agent_loop/bootstrap.py`

---

## Prerequisites

- Anthropic API key configured in `.env`
- `config-base.json` with `"Stage2Model": "claude-haiku-4-5-20251001"` and `"ModeAnalysisEnabled": true`, `"Stage2ClassificationEnabled": true`
- Log level `DEBUG` to observe Stage 2 API calls

---

## Test 1 — Stage 2 classification uses Haiku

**Goal:** Verify that when Stage 2 classification fires, it calls Haiku rather than the main model.

**Steps:**

1. Configure:
   ```json
   {
     "ModeAnalysisEnabled": true,
     "Stage2ClassificationEnabled": true,
     "Stage2Model": "claude-haiku-4-5-20251001",
     "Model": "claude-sonnet-4-5-20250929",
     "LogLevel": "DEBUG"
   }
   ```
2. Start the agent: `python -m micro_x_agent_loop`
3. Submit a prompt that is ambiguous enough to trigger Stage 2 classification (e.g., "Score these 5 items on a scale of 1-10: apples, oranges, bananas, grapes, kiwi")
4. Check DEBUG logs for the Stage 2 classification API call

**Expected:**
- The Stage 2 classification call should show `claude-haiku-4-5-20251001` as the model, not `claude-sonnet-4-5-20250929`
- The main agent response should still use Sonnet
- Classification result (PROMPT or COMPILED) should be reasonable for the input

---

## Test 2 — Classification quality with Haiku

**Goal:** Verify that Haiku produces sensible classifications, not degraded compared to Sonnet.

**Steps:**

1. Same config as Test 1
2. Test with several prompt types:
   - Clear user prompt: "What's the weather like today?" → should classify as PROMPT
   - Batch-like prompt: "For each of these 50 URLs, extract the title and word count" → should detect batch/scoring signals
   - Ambiguous prompt: "Summarise these reviews and rate each one" → should trigger Stage 2

**Expected:**
- Classifications are consistent with what Sonnet would produce
- No obviously wrong classifications (e.g., simple chat classified as COMPILED)

---

## Test 3 — Cost reduction visible in metrics

**Goal:** Verify the cost saving appears in metrics output.

**Steps:**

1. Same config as Test 1, with `"MetricsEnabled": true`
2. Run a session that triggers at least 2 Stage 2 classifications
3. Check `metrics.jsonl` for the classification calls

**Expected:**
- Classification calls should show Haiku pricing ($1/$5 per MTok) not Sonnet pricing ($3/$15 per MTok)
- Status bar should reflect the lower cost for these calls

---
## Notebook Tests
Automated notebook coverage for selected tests in this plan:
- `notebooks/test_tier1_config_and_logic.ipynb` — Cell 1.13 (metrics separation)
