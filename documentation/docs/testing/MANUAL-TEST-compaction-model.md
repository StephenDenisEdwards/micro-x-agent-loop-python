# Manual Test Plan — Strategy 2: Cheap Model for Compaction

**Related review:** [cost-reduction-review.md](../review/cost-reduction-review.md) — Strategy 2
**Code under test:** `src/micro_x_agent_loop/bootstrap.py` lines 56–77; `src/micro_x_agent_loop/compaction.py`

---

## Prerequisites

- Anthropic API key configured in `.env`
- Config with `CompactionStrategy: "summarize"` and `CompactionModel: "claude-haiku-4-5-20251001"`
- Log level `DEBUG` to observe compaction API calls

---

## Test 1 — Compaction uses the configured cheap model

**Goal:** Verify that compaction calls use the `CompactionModel` (Haiku) rather than the main model (Sonnet).

**Steps:**

1. Configure:
   ```json
   {
     "CompactionStrategy": "summarize",
     "CompactionModel": "claude-haiku-4-5-20251001",
     "CompactionThresholdTokens": 2000,
     "Model": "claude-sonnet-4-20250514"
   }
   ```
   (Low threshold to trigger compaction quickly)
2. Start the agent
3. Have a multi-turn conversation (5+ turns with tool use) to exceed the token threshold
4. Check debug logs for the compaction API request

**Expected:**
- Log line: `Compaction API request: model=claude-haiku-4-5-20251001`
- Log line: `Compaction: summarized N messages into ~X tokens, freed ~Y estimated tokens`
- The main LLM calls use `claude-sonnet-4-20250514`
- The compaction call uses `claude-haiku-4-5-20251001`

---

## Test 2 — Compaction model defaults to main model when not set

**Goal:** Verify fallback behaviour when `CompactionModel` is empty or absent.

**Steps:**

1. Configure with `CompactionStrategy: "summarize"` but omit `CompactionModel`
2. Set a low `CompactionThresholdTokens` (e.g., 2000)
3. Trigger compaction via multi-turn conversation
4. Check debug logs

**Expected:**
- Compaction API request uses the main model (e.g., `claude-sonnet-4-20250514`)
- Compaction still succeeds

---

## Test 3 — Compaction cost recorded separately in metrics

**Goal:** Verify that compaction calls appear as distinct entries in `metrics.jsonl`.

**Steps:**

1. Configure with a cheap compaction model and low threshold
2. Trigger compaction
3. Inspect `metrics.jsonl` or run `/cost`

**Expected:**
- A `compaction` metric entry appears with:
  - `estimated_tokens_before` and `estimated_tokens_after`
  - `tokens_freed > 0`
  - `messages_compacted > 0`
- Compaction cost uses Haiku pricing (significantly cheaper than Sonnet)

---

## Test 4 — Summary quality from Haiku

**Goal:** Qualitatively verify that Haiku-generated summaries preserve key context.

**Steps:**

1. Start a session with a specific task (e.g., "search for Python web frameworks and compare Flask vs Django")
2. Have the agent use tools to gather information over several turns
3. Let compaction trigger
4. After compaction, ask the agent a follow-up question that requires information from the compacted context (e.g., "which framework did you recommend and why?")

**Expected:**
- The agent correctly recalls key decisions and data from the compacted conversation
- No hallucinated information or confusion about earlier context
- Conversation continues coherently
