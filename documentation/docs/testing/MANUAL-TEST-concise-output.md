# Manual Test Plan — QW-2: ConciseOutputEnabled

**Related review:** [cost-reduction-review.md](../review/cost-reduction-review.md) — Strategy 9 (Output Token Reduction)
**Code under test:** `src/micro_x_agent_loop/system_prompt.py`

---

## Prerequisites

- Anthropic API key configured in `.env`
- `config-base.json` with `"ConciseOutputEnabled": true`
- Log level `DEBUG` to observe system prompt content

---

## Test 1 — Concise directive present in system prompt

**Goal:** Verify that the concise output directive is included in the system prompt sent to the LLM.

**Steps:**

1. Configure:
   ```json
   {
     "ConciseOutputEnabled": true,
     "LogLevel": "DEBUG"
   }
   ```
2. Start the agent: `python -m micro_x_agent_loop`
3. Submit any prompt
4. Check DEBUG logs for the system prompt content

**Expected:**
- System prompt should contain a directive instructing the model to minimise output verbosity
- The directive should appear after the main system prompt content

---

## Test 2 — Output brevity compared to disabled

**Goal:** Qualitatively assess whether enabling concise mode reduces output token count.

**Steps:**

1. Run with `"ConciseOutputEnabled": false`, ask: "Explain what a hash table is and how it works"
2. Note the output token count from the status bar or metrics
3. Start a new session with `"ConciseOutputEnabled": true`, ask the same question
4. Compare output token counts

**Expected:**
- The concise-enabled response should be noticeably shorter
- The response should still be accurate and complete enough to be useful
- Output token count should be measurably lower (aim for 30–50% reduction)

---

## Test 3 — No quality degradation for tool-using tasks

**Goal:** Verify that concise mode doesn't cause the agent to skip tool calls or produce truncated tool arguments.

**Steps:**

1. Configure with `"ConciseOutputEnabled": true`
2. Ask the agent to perform a multi-step tool task (e.g., "Read the file X and summarise its contents")
3. Observe tool calls and final response

**Expected:**
- Tool calls should be made correctly with proper arguments
- Final response should contain the requested information, just in fewer words
- No skipped steps or incomplete tool arguments
