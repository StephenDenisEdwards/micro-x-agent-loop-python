# Manual Test Plan — Strategy 3: Conversation History Summarisation (Compaction)

**Related review:** [cost-reduction-review.md](../review/cost-reduction-review.md) — Strategy 3
**Code under test:** `src/micro_x_agent_loop/compaction.py`; `src/micro_x_agent_loop/agent.py`

---

## Prerequisites

- Anthropic API key configured in `.env`
- Config with `CompactionStrategy: "summarize"`
- Log level `DEBUG` to observe compaction behaviour

---

## Test 1 — Compaction triggers at threshold

**Goal:** Verify compaction fires when estimated tokens exceed `CompactionThresholdTokens`.

**Steps:**

1. Set `CompactionThresholdTokens: 3000` (low, for easy triggering)
2. Start the agent and send several prompts that generate verbose tool output
3. Monitor logs for compaction trigger

**Expected:**
- Log: `Compaction: estimated ~X tokens, threshold 3,000 — compacting N messages`
- Log: `Compaction: summarized N messages into ~Y tokens, freed ~Z estimated tokens`
- After compaction, message history is shorter (verify via `/debug` or log output)

---

## Test 2 — No compaction below threshold

**Goal:** Verify compaction does NOT fire when under the threshold.

**Steps:**

1. Set `CompactionThresholdTokens: 200000` (very high)
2. Have a short conversation (2–3 turns)
3. Check logs

**Expected:**
- No compaction log lines appear
- Full message history is preserved

---

## Test 3 — Smart compaction trigger uses actual API token counts

**Goal:** Verify that `SmartCompactionTriggerEnabled: true` uses actual API-reported token counts instead of tiktoken estimates.

**Steps:**

1. Configure:
   ```json
   {
     "CompactionStrategy": "summarize",
     "SmartCompactionTriggerEnabled": true,
     "CompactionThresholdTokens": 5000
   }
   ```
2. Have a multi-turn conversation with tool use
3. Observe debug logs for actual vs estimated token counts

**Expected:**
- After the first LLM response, actual input tokens are fed to the compaction strategy
- Compaction triggers based on actual tokens (which may differ from tiktoken estimate by 10–20%)

---

## Test 4 — Compaction preserves tool use/result pairs

**Goal:** Verify the boundary adjustment logic doesn't split a tool_use from its tool_result.

**Steps:**

1. Set a low compaction threshold
2. Have a conversation where the last few messages include assistant tool_use followed by tool_result
3. Trigger compaction

**Expected:**
- The protected tail messages include complete tool_use/tool_result pairs
- No orphaned tool_use without its corresponding tool_result in the remaining messages
- No API error about mismatched tool_use/tool_result blocks

---

## Test 5 — Context preserved after compaction

**Goal:** Verify the agent can still reference information from before compaction.

**Steps:**

1. In turn 1, tell the agent a specific fact: "My project name is AlphaOmega and the deploy target is us-east-1"
2. Have several more turns (with tool use) to trigger compaction
3. After compaction triggers, ask: "What is my project name and deploy target?"

**Expected:**
- The `[CONTEXT SUMMARY]` block in the compacted history includes the key facts
- The agent correctly answers with "AlphaOmega" and "us-east-1"

---

## Test 6 — Compaction fallback on error

**Goal:** Verify graceful fallback when the compaction LLM call fails.

**Steps:**

1. Configure compaction with an invalid `CompactionModel` (e.g., `"nonexistent-model-id"`)
2. Set a low threshold and trigger compaction

**Expected:**
- Log warning: `Compaction failed: ... Falling back to history trimming.`
- Original messages are preserved unchanged
- The agent continues functioning normally

---

## Test 7 — Compaction with `CompactionStrategy: "none"`

**Goal:** Verify that setting strategy to `"none"` disables compaction entirely.

**Steps:**

1. Set `CompactionStrategy: "none"`
2. Have a long conversation exceeding what would normally trigger compaction
3. Check logs

**Expected:**
- No compaction log lines
- Message history grows unbounded (until API context window limit)

---

## Test 8 — Role alternation after compaction

**Goal:** Verify that the rebuilt message list maintains valid user/assistant alternation.

**Steps:**

1. Trigger compaction in a conversation where the tail starts with a user message
2. Continue the conversation after compaction

**Expected:**
- An assistant acknowledgment message (`"Understood. Continuing with the current task."`) is inserted if needed
- No API error about consecutive same-role messages
- Conversation continues normally

---
## Test 9 — `/compact` command forces compaction

**Goal:** Verify that `/compact` forces compaction regardless of threshold, and `tail N` overrides protected tail messages.

**Steps:**

1. Set `CompactionThresholdTokens: 200000` (very high, so auto-compaction won't trigger)
2. Have a multi-turn conversation with tool use (5+ turns to build up context)
3. Run `/compact` — observe it compacts with default `ProtectedTailMessages`
4. Continue conversation to build up context again
5. Run `/compact tail 2` — observe it compacts more aggressively

**Expected:**
- `/compact` fires compaction even though threshold is not reached
- Log: `Compaction: estimated ~X tokens, threshold 0 — compacting N messages`
- `/compact tail 2` compacts more messages than the default (only 2 tail messages protected)
- After compaction, the status bar shows updated `ctx <tokens>tok/<N>msg`
- Conversation continues normally after compaction

---

## Test 10 — Context size in status bar

**Goal:** Verify the bottom toolbar displays current context token/message count.

**Steps:**

1. Start the agent with `StatusBarEnabled: true`
2. Send a few messages
3. Observe the bottom toolbar after each turn

**Expected:**
- Toolbar shows `ctx <N>tok/<M>msg` segment alongside cost and model info
- Values update after each turn and after `/compact`

---

## Notebook Tests
Automated notebook coverage for selected tests in this plan:
- `notebooks/test_tier1_config_and_logic.ipynb` — Cells 1.8 (none strategy), 1.9 (summarize trigger), 1.10 (role alternation)
- `notebooks/test_tier2_live_api.ipynb` — Cell 2.4 (fact recall after summarization)
