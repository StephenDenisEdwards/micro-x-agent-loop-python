# Manual Test Plan — Session Budget Caps

**Related review:** [cost-reduction-review.md](../review/cost-reduction-review.md) — Strategy 4 (Cost Tracking and Visibility)
**Code under test:** `src/micro_x_agent_loop/agent.py` (budget check + warning), `src/micro_x_agent_loop/metrics.py` (toolbar display)

---

## Prerequisites

- Anthropic API key configured in `.env`
- `config-base.json` accessible
- Log level `DEBUG` to observe budget messages

---

## Test 1 — Budget warning at 80%

**Goal:** Verify a warning is emitted when session spending crosses 80% of the budget.

**Steps:**

1. Configure a low budget to trigger quickly:
   ```json
   {
     "SessionBudgetUSD": 0.01
   }
   ```
2. Start the agent: `python -m micro_x_agent_loop`
3. Submit a prompt that will cost at least $0.008 (e.g., a multi-sentence question)

**Expected:**
- A `[Budget]` warning message appears after the API call that crosses 80%
- The warning shows the percentage and dollar amounts
- The warning appears only once — subsequent turns do not repeat it

---

## Test 2 — Budget hard stop at 100%

**Goal:** Verify the agent refuses to start a new turn when the budget is exhausted.

**Steps:**

1. Same low budget config as Test 1 (`"SessionBudgetUSD": 0.01`)
2. Start the agent and submit prompts until spending exceeds $0.01
3. Submit another prompt after the budget is exceeded

**Expected:**
- The agent prints a message: "Session budget exhausted (${spent} / ${budget})"
- The turn does NOT execute — no API call is made
- The agent suggests using `/cost` for details or starting a new session
- The REPL remains responsive (not hung)

---

## Test 3 — Status bar shows budget percentage

**Goal:** Verify the CLI status bar displays budget information when a budget is set.

**Steps:**

1. Configure: `"SessionBudgetUSD": 1.00`, `"StatusBarEnabled": true`
2. Start the agent and submit a prompt
3. Observe the bottom toolbar after the response

**Expected:**
- The toolbar shows cost in the format `$X.XXX/$1.00 (Y%)`
- The percentage updates after each turn
- When no budget is set (0.0), the toolbar shows just `$X.XXX` without the budget fraction

---

## Test 4 — No budget (default behaviour)

**Goal:** Verify that with no budget set (default 0.0), there are no warnings or stops.

**Steps:**

1. Ensure `SessionBudgetUSD` is `0.0` or absent from config
2. Start the agent and submit multiple prompts

**Expected:**
- No budget warnings appear regardless of spending
- No turns are blocked
- The status bar shows cost without budget percentage

---

## Test 5 — Budget resets on session reset

**Goal:** Verify that starting a new session resets the budget counter.

**Steps:**

1. Configure `"SessionBudgetUSD": 0.02`
2. Start the agent and use enough turns to get close to the budget
3. Run `/session new` to start a new session
4. Submit a prompt

**Expected:**
- The budget counter resets — the new session starts at $0
- The warning flag resets — a new 80% warning can be emitted
- The turn executes normally

---
## Notebook Tests
Automated notebook coverage for selected tests in this plan:
- `notebooks/test_tier1_config_and_logic.ipynb` — Cell 1.11 (no budget configured)
- `notebooks/test_tier2_live_api.ipynb` — Cell 2.3 (budget exhaustion)
