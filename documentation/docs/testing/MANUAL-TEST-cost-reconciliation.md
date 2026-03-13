# Manual Test Plan — Cost Reconciliation & Metrics Persistence

**Related design:** [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md)
**Code under test:** `src/micro_x_agent_loop/cost_reconciliation.py`, `src/micro_x_agent_loop/commands/command_handler.py`, `src/micro_x_agent_loop/memory/facade.py`, `src/micro_x_agent_loop/agent.py`

---

## Prerequisites

- Anthropic API key configured in `.env`
- `ANTHROPIC_ADMIN_API_KEY` set in `.env` (required for the `anthropic-admin` MCP server to query billing data)
- `config-base.json` with `MemoryEnabled: true`, `MetricsEnabled: true`, and the `anthropic-admin` MCP server configured
- The `metrics` log consumer configured in `LogConsumers`
- At least one prior session with API calls recorded (for reconciliation to have data)
- Python 3.11+ with the agent installed (`pip install -e .`)

> **Cost awareness**
> These tests make real LLM API calls. Budget approximately $0.02-$0.10 for a full test run.

---

## Part A: Metrics Persistence to SQLite

### Test A.1 — API call events are persisted to SQLite

**Goal:** Verify that `metric.api_call` events are written to the SQLite events table after each LLM call.

**Steps:**

1. Start the agent: `python -m micro_x_agent_loop`
2. Send a simple prompt: `What is 2 + 2?`
3. Exit the agent (Ctrl+D or `/quit`)
4. Query the events table:
   ```bash
   sqlite3 .micro_x/memory.db "SELECT type, substr(payload_json, 1, 120) FROM events WHERE type = 'metric.api_call' ORDER BY created_at DESC LIMIT 5;"
   ```

**Expected:**
- At least one row with `type = 'metric.api_call'`
- The `payload_json` contains JSON with fields: `type`, `timestamp`, `session_id`, `model`, `input_tokens`, `output_tokens`, `estimated_cost_usd`
- The `estimated_cost_usd` value is > 0 (assuming a known model is configured)

### Test A.2 — Compaction events are persisted to SQLite

**Goal:** Verify that `metric.compaction` events are written when compaction occurs.

**Steps:**

1. Configure a low compaction threshold:
   ```json
   {
     "CompactionThresholdTokens": 20000,
     "CompactionStrategy": "summarize"
   }
   ```
2. Start the agent and send several prompts with tool calls to build up context until compaction triggers
3. Exit the agent
4. Query:
   ```bash
   sqlite3 .micro_x/memory.db "SELECT type, substr(payload_json, 1, 120) FROM events WHERE type = 'metric.compaction' ORDER BY created_at DESC LIMIT 5;"
   ```

**Expected:**
- At least one row with `type = 'metric.compaction'`
- Payload includes `tokens_before`, `tokens_after`, `tokens_freed`, `compaction_cost_usd`

### Test A.3 — Session summary events are persisted on shutdown

**Goal:** Verify that `metric.session_summary` is written when the agent shuts down.

**Steps:**

1. Start the agent, send at least one prompt, then exit cleanly (Ctrl+D)
2. Query:
   ```bash
   sqlite3 .micro_x/memory.db "SELECT type, substr(payload_json, 1, 200) FROM events WHERE type = 'metric.session_summary' ORDER BY created_at DESC LIMIT 3;"
   ```

**Expected:**
- At least one row with `type = 'metric.session_summary'`
- Payload includes `total_turns`, `total_cost_usd`, `total_api_calls`, `total_tool_calls`, `model_subtotals`

### Test A.4 — Metrics also written to metrics.jsonl

**Goal:** Verify dual-write: events go to both SQLite and the metrics log file.

**Steps:**

1. After Test A.1, check the metrics log file:
   ```bash
   tail -5 C:\Users\steph\source\repos\resources\micro-x-agent-loop-logs\metrics.jsonl
   ```
   (Adjust path to match your `LogConsumers` config.)

**Expected:**
- The file contains JSON lines with `"type": "api_call"` entries
- The records match what was written to the events table (same session_id, similar timestamps)

---

## Part B: `/cost reconcile` Command — Error Handling

### Test B.1 — `/cost reconcile` with no local data

**Goal:** Verify graceful handling when there are no local metric events for the lookback period.

**Steps:**

1. Start a fresh agent session
2. Run: `/cost reconcile 0`

**Expected:**
- Output shows "No local metric.api_call events found for this period."
- No crash or traceback

### Test B.2 — `/cost reconcile` without anthropic-admin MCP server

**Goal:** Verify graceful handling when the reconciliation tool is not available.

**Steps:**

1. Start the agent with a config that does NOT include the `anthropic-admin` MCP server
2. Run: `/cost reconcile`

**Expected:**
- Output shows "Error: anthropic-admin MCP server not available."
- Followed by: "Tool 'anthropic-admin__anthropic_usage' not found in tool_map."
- Followed by: "Ensure the anthropic-admin MCP server is configured and running."

### Test B.3 — `/cost reconcile` without memory enabled

**Goal:** Verify graceful handling when memory is disabled.

**Steps:**

1. Start the agent with `MemoryEnabled: false`
2. Run: `/cost reconcile`

**Expected:**
- Output shows "Error: Memory not enabled — no local cost events to compare."
- Followed by: "Enable MemoryEnabled=true in config."

### Test B.4 — `/cost reconcile` invalid days argument

**Goal:** Verify error handling for bad input.

**Steps:**

1. Run: `/cost reconcile abc`

**Expected:**
- Output shows "Usage: /cost reconcile [days] [--start YYYY-MM-DD] [--end YYYY-MM-DD]"
- No crash

### Test B.5a — `/cost reconcile` invalid date format

**Goal:** Verify error handling for bad date strings.

**Steps:**

1. Run: `/cost reconcile --start 03-2026-01`

**Expected:**
- Output shows "Invalid date format: ..."
- Followed by: "Use YYYY-MM-DD (e.g. 2026-03-01)"
- No crash

### Test B.5 — `/cost reconcile` with missing admin API key

**Goal:** Verify error handling when the Anthropic admin API key is not set.

**Steps:**

1. Temporarily unset `ANTHROPIC_ADMIN_API_KEY` from your environment
2. Restart the agent so the anthropic-admin MCP server starts without the key
3. Run: `/cost reconcile`

**Expected:**
- Output shows an error from the Anthropic API call (e.g. "Anthropic API error: ...")
- Suggests checking that `ANTHROPIC_ADMIN_API_KEY` is set
- No crash or hang

---

## Part C: `/cost reconcile` Command — Happy Path

> **Important:** These tests only work with the Anthropic provider. The reconciliation compares local estimates against Anthropic's `/v1/organizations/cost_report` billing endpoint. There is no equivalent for OpenAI or other providers.

### Test C.1 — Generate local cost data for reconciliation

**Goal:** Seed the SQLite events table with `metric.api_call` events so subsequent reconciliation tests have data to compare.

**Steps:**

1. Ensure config uses an Anthropic model (e.g. `claude-sonnet-4-5-20250929`)
2. Start the agent: `python -m micro_x_agent_loop`
3. Send 3-5 prompts of varying complexity:
   ```
   What is 2 + 2?
   List the top 5 largest countries by area.
   Write a Python function that checks if a string is a palindrome.
   ```
4. Run `/cost` and note the total estimated cost
5. Exit the agent

**Verify local data exists:**
```bash
sqlite3 .micro_x/memory.db "SELECT COUNT(*), SUM(json_extract(payload_json, '$.estimated_cost_usd')) FROM events WHERE type = 'metric.api_call' AND created_at >= datetime('now', '-1 day');"
```

**Expected:**
- Count > 0 (at least 3 rows)
- Sum > $0 (matches approximately what `/cost` reported)

### Test C.2 — `/cost reconcile` with 1-day lookback (default)

**Goal:** Verify end-to-end reconciliation against the Anthropic billing API for yesterday's data.

**Steps:**

1. Start the agent: `python -m micro_x_agent_loop`
2. Run: `/cost reconcile`

**Expected output structure (per-model view — when usage report succeeds):**
```
Cost Reconciliation: YYYY-MM-DD to YYYY-MM-DD
------------------------------------------------------------
Querying Anthropic billing API...

Date         Model                               Ours    Anthropic     Diff Status
------------------------------------------------------------
YYYY-MM-DD   sonnet-4-5-20250929                $X.XXXX   $Y.YYYY    Z.Z%  OK
------------------------------------------------------------
TOTAL                                           $X.XXXX   $Y.YYYY
Overall divergence: Z.Z% — OK

All costs within threshold. Pricing table appears accurate.
```

**Expected output structure (daily aggregate view — when per-model data unavailable):**
```
Cost Reconciliation: YYYY-MM-DD to YYYY-MM-DD
------------------------------------------------------------
Querying Anthropic billing API...

(Per-model Anthropic data unavailable — showing daily aggregates)

Date            Ours    Anthropic     Diff Status
-------------------------------------------------
YYYY-MM-DD   $X.XXXX   $Y.YYYY    Z.Z%  OK
-------------------------------------------------
TOTAL        $X.XXXX   $Y.YYYY

Local per-model breakdown:
  sonnet-4-5-20250929                      $   X.XXXX
```

**Verify:**
- The header shows yesterday's date to today's date
- "Querying Anthropic billing API..." message appears before the table
- The "Ours" column values are > $0 (from local events)
- The "Anthropic" column values are > $0 (from the billing API) — if they show $0, check that the API response is being parsed correctly (the API uses a nested time-bucket/results structure)
- Each row has a percentage in the "Diff" column
- Rows within 5% show "OK", rows beyond 5% show "MISMATCH"
- A TOTAL row sums both columns
- An overall divergence percentage and status are shown
- If all rows are OK: "All costs within threshold. Pricing table appears accurate."

### Test C.3 — `/cost reconcile` with custom day range

**Goal:** Verify the days parameter controls the lookback window.

**Steps:**

1. Run: `/cost reconcile 7`

**Expected:**
- Header shows a 7-day range (e.g. "2026-03-06 to 2026-03-13")
- Multiple date rows appear in the table (one per day that had API usage)
- More data than the 1-day reconciliation
- Models are listed per-date (e.g. the same model may appear on multiple dates)

2. Run: `/cost reconcile 1`

**Expected:**
- Header shows a 1-day range
- Fewer rows than the 7-day reconciliation

### Test C.3a — `/cost reconcile` with --start and --end dates

**Goal:** Verify explicit date range parameters work.

**Steps:**

1. Run: `/cost reconcile --start 2026-03-01 --end 2026-03-10`

**Expected:**
- Header shows "Cost Reconciliation: 2026-03-01 to 2026-03-11" (end is inclusive, internal range extends to next day)
- Only data within the specified date range appears
- No data from before March 1st or after March 10th

### Test C.3b — `/cost reconcile` with --start only

**Goal:** Verify that --start without --end defaults to today.

**Steps:**

1. Run: `/cost reconcile --start 2026-03-01`

**Expected:**
- Header starts at 2026-03-01 and ends at tomorrow's date
- Covers all data from March 1st through today

### Test C.3c — `/cost reconcile` with --from/--to aliases

**Goal:** Verify the `--from` and `--to` aliases work identically to `--start` and `--end`.

**Steps:**

1. Run: `/cost reconcile --from 2026-03-05 --to 2026-03-10`

**Expected:**
- Same behaviour as `--start 2026-03-05 --end 2026-03-10`

### Test C.4 — Verify model name shortening in output

**Goal:** Confirm that long model IDs are shortened for display readability.

**Steps:**

1. Run `/cost reconcile 7` (or however many days have data)
2. Examine the Model column

**Expected:**
- The `claude-` prefix is stripped from model names (e.g. `sonnet-4-5-20250929` not `claude-sonnet-4-5-20250929`)
- The `anthropic/claude-` prefix is also stripped if present
- Model names fit within the 35-character column width

### Test C.5 — Cross-check local totals against `/cost` from a known session

**Goal:** Verify that the local cost data in the reconciliation report is consistent with what `/cost` showed during the session.

**Steps:**

1. Start a new agent session
2. Send 2-3 prompts
3. Run `/cost` and record the "Total cost" value (e.g. $0.0234)
4. Exit the agent
5. Start a new session and run: `/cost reconcile`
6. Find today's date row(s) in the output

**Expected:**
- The "Ours" total should include (at minimum) the cost from step 3
- If this was the only session today, the "Ours" total should approximately equal the `/cost` total
- If there were other sessions today, "Ours" will be higher (it aggregates all sessions in the date range)

### Test C.6 — Interpret MISMATCH results

**Goal:** Understand what a MISMATCH means and verify the divergence calculation.

**Steps:**

1. Run `/cost reconcile 7`
2. Look for any rows with "MISMATCH" status

**If MISMATCHes exist:**
- The Diff column shows > 5.0%
- Calculate manually: `abs(Ours - Anthropic) / Anthropic * 100` — should match the displayed percentage
- Common causes of mismatch:
  - Pricing table in config is outdated (rates changed)
  - Cache token pricing differs from what Anthropic actually charges
  - Rounding differences on very small amounts
- The summary line shows how many model/date combinations exceeded the threshold

**If no MISMATCHes exist:**
- All Diff values are <= 5.0%
- Summary says "All costs within threshold. Pricing table appears accurate."
- This confirms the `Pricing` table in `config-base.json` is correct

### Test C.7 — Reconcile with multi-model usage

**Goal:** Verify reconciliation handles sessions that used multiple models (e.g. main model + compaction model + sub-agent model).

**Steps:**

1. Configure:
   ```json
   {
     "Model": "claude-sonnet-4-5-20250929",
     "CompactionModel": "claude-haiku-4-5-20251001",
     "SubAgentsEnabled": true,
     "SubAgentModel": "claude-haiku-4-5-20251001",
     "CompactionThresholdTokens": 20000
   }
   ```
2. Start the agent and generate enough conversation to trigger compaction and/or sub-agent calls
3. Exit the agent
4. Start a new session and run: `/cost reconcile`

**Expected:**
- The table shows multiple model rows for the same date (e.g. both `sonnet-4-5-20250929` and `haiku-4-5-20251001`)
- Each model has its own Ours/Anthropic/Diff values
- The TOTAL line sums across all models
- Both models should show OK if the pricing table is correct

### Test C.8 — Reconcile when Anthropic reports $0

**Goal:** Verify handling when Anthropic's billing API returns zero cost (e.g. free tier, credits, or data not yet available).

**Steps:**

1. Run `/cost reconcile` shortly after generating data (billing data may have a delay)

**Expected if Anthropic returns $0:**
- The "Anthropic" column shows $0.0000
- The output shows: "Anthropic reported $0 — cannot calculate divergence."
- No division-by-zero error
- Local "Ours" values are still displayed correctly

### Test C.9 — Reconcile with only Anthropic data (no local data for that model)

**Goal:** Verify handling when Anthropic reports costs for a model we have no local events for (e.g. API calls made outside this agent).

**Steps:**

1. Make API calls using a different tool or the Anthropic console (not through the agent)
2. Run `/cost reconcile` in the agent

**Expected:**
- The model appears in the table with $0.0000 in the "Ours" column
- The "Anthropic" column shows the actual cost
- The Diff is 100.0% and status is "MISMATCH"
- This is correct — we have no local tracking for calls made outside the agent

---

## Part D: `/cost reconcile` — Operational Scenarios

### Test D.1 — Use reconciliation to validate a pricing table update

**Goal:** Demonstrate the workflow for verifying pricing accuracy after updating the pricing table.

**Steps:**

1. Run `/cost reconcile 7` and note any MISMATCH rows
2. If mismatches exist, check the model's pricing in `config-base.json`:
   ```json
   "anthropic/claude-sonnet-4-5-20250929": { "input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_create": 3.75 }
   ```
3. Cross-reference with current Anthropic pricing at https://docs.anthropic.com/en/docs/about-claude/models
4. If the pricing is wrong, update `config-base.json` and restart the agent
5. Run `/cost reconcile 7` again

**Expected:**
- After correcting pricing, the MISMATCH should become OK (or closer to OK)
- Note: correcting the pricing table only affects future cost estimates — historical events in SQLite retain the old estimated_cost_usd values

### Test D.2 — Daily reconciliation check

**Goal:** Demonstrate the recommended daily workflow for cost monitoring.

**Steps:**

1. Start the agent each morning
2. Run: `/cost reconcile`
3. Review the output

**Expected:**
- If all OK: pricing is accurate, no action needed
- If MISMATCH: investigate whether Anthropic changed their pricing or if there's a bug in cost estimation
- If "No local metric.api_call events": no Anthropic API calls were made yesterday — this is normal on days without usage

### Test D.3 — Reconcile after a high-spend period

**Goal:** Verify reconciliation works correctly after a period of intensive usage.

**Steps:**

1. After a day with significant API usage (e.g. $1+), run: `/cost reconcile`
2. Compare the TOTAL row

**Expected:**
- Both "Ours" and "Anthropic" totals are in the same ballpark
- Overall divergence should be < 5% if the pricing table is correct
- Larger absolute differences are expected (5% of $1 = $0.05) but the percentage should remain stable

---

## Part E: `/cost` Command Help & Backwards Compatibility

### Test E.1 — Help text shows reconcile subcommand

**Steps:**

1. Start the agent
2. Run: `/help`

**Expected:**
- The help output includes both:
  - `/cost`
  - `/cost reconcile [days]`

### Test E.2 — `/cost` without arguments still shows session summary

**Steps:**

1. Start the agent, send a prompt
2. Run: `/cost`

**Expected:**
- The existing session cost summary is displayed (same as before)
- No change in behaviour from the original `/cost` command

---

## Part F: Unit Tests

### Test F.1 — estimate_cost unit tests cover all models

**Steps:**

```bash
python -m pytest tests/test_usage.py -v
```

**Expected:**
- All tests pass
- `EstimateCostAllModelsTests` includes one test per model in the pricing table
- `test_every_config_model_has_a_test` passes (no missing model coverage)
- `test_no_extra_test_models` passes (no stale test entries)

### Test F.2 — Facade tests pass with store property

**Steps:**

```bash
python -m pytest tests/memory/test_facade.py -v
```

**Expected:**
- All tests pass
- `NullMemoryFacade` and `ActiveMemoryFacade` both expose a `store` property

### Test F.3 — Command handler tests pass

**Steps:**

```bash
python -m pytest tests/test_command_handler.py -v
```

**Expected:**
- All tests pass, including existing `/cost` test
