# Manual Test Plan — Per-Turn Model Routing

**Related plan:** [PLAN-cost-reduction.md](../planning/PLAN-cost-reduction.md) — Phase 3b
**Code under test:** `src/micro_x_agent_loop/turn_classifier.py`, `src/micro_x_agent_loop/turn_engine.py` (routing logic), `src/micro_x_agent_loop/agent.py` (wiring)

---

## Prerequisites

- Anthropic API key configured in `.env`
- `config-base.json` accessible
- Log level `DEBUG` to observe routing decisions

---

## Test 1 — Routing disabled (default)

**Goal:** Verify that with routing disabled (default), all turns use the main model.

**Steps:**

1. Ensure `PerTurnRoutingEnabled` is `false` or absent from config
2. Start the agent: `python -m micro_x_agent_loop`
3. Submit several prompts, including tool-using prompts
4. Check `/cost` for model breakdown

**Expected:**
- All API calls use the main model (Sonnet)
- No "Turn routing" messages in logs
- `/cost` shows only one model in the breakdown

---

## Test 2 — Simple tool-result continuation routes to cheap model

**Goal:** Verify that after tool execution, the continuation call uses the cheap model.

**Steps:**

1. Configure:
   ```json
   {
     "PerTurnRoutingEnabled": true,
     "PerTurnRoutingModel": "claude-haiku-4-5-20251001",
     "PerTurnRoutingProvider": "anthropic"
   }
   ```
2. Start the agent with `LogLevel: "DEBUG"`
3. Submit a prompt that triggers a tool call (e.g., "read the file config.json")
4. Observe the logs

**Expected:**
- First LLM call (iteration 0) uses the main model (Sonnet)
- Continuation call after tool result (iteration 1+) uses Haiku
- Logs show: `Turn routing: model=claude-haiku-4-5-20251001 rule=tool_result_continuation`
- `/cost` shows both models in the breakdown

---

## Test 3 — Complexity keywords keep main model

**Goal:** Verify that complex prompts use the main model even during tool-result continuations.

**Steps:**

1. Same config as Test 2 (routing enabled)
2. Submit: "analyze the structure of config.json and explain why it's organized this way"
3. Observe the logs

**Expected:**
- The complexity keyword "analyze" or "explain why" triggers the complexity guard
- All LLM calls use the main model (Sonnet)
- Logs show: `rule=complexity_guard`

---

## Test 4 — Short follow-up routes to cheap model

**Goal:** Verify that short follow-up messages in turn 2+ use the cheap model.

**Steps:**

1. Same config as Test 2 (routing enabled)
2. Submit a first prompt (any prompt)
3. Submit a short follow-up: "yes" or "continue" or "ok"
4. Observe the logs

**Expected:**
- First turn: main model (no rule matches or default)
- Follow-up turn: cheap model (rule: `short_followup`)
- Logs show model and rule for each call

---

## Test 5 — Cost savings observable in /cost

**Goal:** Verify that per-turn routing produces measurable cost savings.

**Steps:**

1. Same config as Test 2 (routing enabled)
2. Submit 3-5 prompts that trigger tool calls
3. Run `/cost`

**Expected:**
- Model breakdown shows both Sonnet and Haiku
- Haiku calls have lower cost per call
- `call_type` shows `main` and `main:routed` in per-call breakdown
- Total session cost is lower than an equivalent session without routing

---

## Test 6 — Configuration validation

**Goal:** Verify that enabling routing without required fields fails early.

**Steps:**

1. Set `PerTurnRoutingEnabled: true` but omit `PerTurnRoutingModel`
2. Start the agent

**Expected:**
- Agent fails to start with: "PerTurnRoutingModel must be set in config when PerTurnRoutingEnabled is true"

---

## Test 7 — Custom complexity keywords

**Goal:** Verify that custom keywords override the defaults.

**Steps:**

1. Configure:
   ```json
   {
     "PerTurnRoutingEnabled": true,
     "PerTurnRoutingModel": "claude-haiku-4-5-20251001",
     "PerTurnRoutingProvider": "anthropic",
     "PerTurnRoutingComplexityKeywords": "foo,bar"
   }
   ```
2. Submit: "design a system" (would normally be blocked by default keywords)
3. Submit: "foo the thing"

**Expected:**
- "design a system" is NOT blocked (not in custom keywords) — may route to cheap model if other rules match
- "foo the thing" IS blocked by complexity guard

---
## Notebook Tests
Automated notebook coverage for selected tests in this plan:
- `notebooks/test_tier1_config_and_logic.ipynb` — Cells 1.6 (classify_turn rules), 1.7 (config validation)
