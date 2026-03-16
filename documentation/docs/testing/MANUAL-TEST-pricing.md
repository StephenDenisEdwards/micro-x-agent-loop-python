# Pricing & Cost Tracking — Manual Test Plan

Step-by-step walkthrough of the pricing lookup, cost estimation, session accumulator, and `/cost` command. Run these from the project root directory using the interactive REPL.

> **Prerequisites**
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - A working `config.json` with at least one LLM provider configured
> - `.env` with valid API keys

> **Cost awareness**
> These tests make real LLM API calls. Budget approximately $0.02–$0.10 for a full test run with Sonnet or Haiku.

---

## 1. Baseline Cost Reporting

### Test 1.1: `/cost` shows session summary after a single turn

Start the agent:
```bash
python -m micro_x_agent_loop
```

Send a simple prompt:
```
What is 2 + 2?
```

Then run:
```
/cost
```

**Expected:**
- Output shows "Session Cost Summary" with non-zero values for:
  - Provider/Model (matches your configured provider)
  - Pricing per MTok line (input/output/cache_read/cache_write rates)
  - Total API calls: 1
  - Input tokens > 0
  - Output tokens > 0
  - Total cost > $0.000000
  - Total duration > 0 ms
  - Per-call breakdown with one entry

### Test 1.2: `/cost` accumulates across multiple turns

Send 2–3 more prompts (e.g., "What is 3 + 3?", "What is 4 + 4?").

Run `/cost` again.

**Expected:**
- Total API calls incremented (3–4 depending on mode analysis calls)
- Total cost increased from Test 1.1
- Per-call breakdown shows multiple entries with increasing call numbers
- Each entry shows turn number, model, token counts, and individual cost

### Test 1.3: `/cost` resets on new session

Run:
```
/session new
```

Then run `/cost`.

**Expected:**
- All counters reset to zero
- Total cost: $0.000000
- No per-call breakdown entries

---

## 2. Pricing Lookup

### Test 2.1: Known Anthropic model shows pricing

Start the agent with an Anthropic model (e.g., `claude-sonnet-4-6` or `claude-haiku-4-5`).

Send any prompt, then run `/cost`.

**Expected:**
- "Pricing (per MTok)" line shows the correct rates for the model
- Sonnet 4.6: in=$3.0 out=$15.0 cache_read=$0.3 cache_write=$3.75
- Haiku 4.5: in=$1.0 out=$5.0 cache_read=$0.1 cache_write=$1.25

### Test 2.2: Known OpenAI model shows pricing

Start the agent with `--config` pointing to an OpenAI config (e.g., `config-standard-openai-no-console.json`).

Send any prompt, then run `/cost`.

**Expected:**
- "Pricing (per MTok)" line shows OpenAI rates
- gpt-4.1: in=$2.0 out=$8.0 cache_read=$0.5 cache_write=$0.0

### Test 2.3: Unknown model shows $0 warning

If you have access to a model not in the pricing table (e.g., a fine-tuned or local model), configure it and send a prompt.

Run `/cost`.

**Expected:**
- "Pricing (per MTok): (unknown model — cost estimated as $0)" message appears
- A one-time warning is logged: `No pricing data for model '<name>' — cost will be reported as $0. Add it to the Pricing section in config.json.`
- The warning only appears once per model per session (subsequent calls for the same model are silent)
- Total cost remains $0.000000
- Token counts are still tracked correctly (just cost is zero)

**Fix:** Add the model to the `Pricing` section in `config.json` (or `config-base.json`) with its per-million-token rates.

---

## 3. Cache Token Tracking

### Test 3.1: Cache tokens appear after multiple turns (Anthropic only)

Start the agent with an Anthropic model and prompt caching enabled (`PromptCaching: true`).

Send 3+ prompts in the same session.

Run `/cost`.

**Expected:**
- "Cache read tokens" shows a non-zero value (the stable prefix — system prompt + tool schemas — should be cached from turn 2 onwards)
- "Cache create tokens" shows a non-zero value (from the first turn that established the cache)
- Per-call breakdown shows `cr=N` and/or `cw=N` annotations on relevant calls
- Total cost reflects the discounted cache pricing (lower than if all tokens were full-price input)

### Test 3.2: Cache tokens are zero for OpenAI

Start the agent with an OpenAI model.

Send 2+ prompts, then run `/cost`.

**Expected:**
- Cache read tokens: 0
- Cache create tokens: 0
- (OpenAI caching is server-side and not reported in the same way)

---

## 4. Multi-Model Tracking

### Test 4.1: Compaction uses a different model

Configure compaction with a cheaper model:
```json
{
  "CompactionModel": "claude-haiku-4-5-20251001",
  "CompactionStrategy": "summarize",
  "CompactionThresholdTokens": 20000
}
```

Generate enough conversation to trigger compaction (send several prompts with tool calls that produce large results, or set a low threshold).

Run `/cost`.

**Expected:**
- "Model breakdown" section appears (because >1 model was used)
- Lists both the main model and the compaction model with separate token/cost subtotals
- Compaction events count > 0

### Test 4.2: Sub-agent uses a different model

Configure sub-agents with a cheaper model:
```json
{
  "SubAgentsEnabled": true,
  "SubAgentModel": "claude-haiku-4-5-20251001"
}
```

Send a prompt that triggers sub-agent delegation (e.g., "Read all the files in the src directory and summarize the architecture").

Run `/cost`.

**Expected:**
- "Model breakdown" section shows both models
- Sub-agent model shows its own call count and cost
- Per-call breakdown distinguishes sub-agent calls (call_type includes sub-agent context)

---

## 5. Tool Call Tracking

### Test 5.1: Tool calls appear in breakdown

Send a prompt that uses tools (e.g., "List the files in the current directory").

Run `/cost`.

**Expected:**
- "Tool calls: N (0 errors)" with N > 0
- "Tool breakdown" section lists tool names with call counts

### Test 5.2: Tool errors are counted

Send a prompt that will cause a tool error (e.g., ask the agent to read a non-existent file `/tmp/does_not_exist_xyz.txt`).

Run `/cost`.

**Expected:**
- Tool errors count incremented
- Tool breakdown still shows the failed tool's call count

---

## 6. Metrics Log File

### Test 5.3: Unit test coverage for all models

Run the pricing unit tests:

```bash
python -m pytest tests/test_usage.py::EstimateCostAllModelsTests -v
```

**Expected:**
- One test per model in the `Pricing` section of `config-base.json` (18 models as of March 2026)
- `test_every_config_model_has_a_test` passes — every config model has test coverage
- `test_no_extra_test_models` passes — no test references a removed model
- Each model test uses standard token counts (10k input, 5k output, 50k cache read, 2k cache create) and asserts the expected cost to 6 decimal places

### Test 6.1: metrics.jsonl is written

After running any of the tests above, check for a `metrics.jsonl` file in the project root (or the configured log output location).

```bash
tail -5 metrics.jsonl
```

**Expected:**
- File exists and contains JSON lines
- Each line has a `"type"` field: `"api_call"`, `"tool_execution"`, or `"compaction"`
- `api_call` records include: session_id, turn_number, model, input_tokens, output_tokens, estimated_cost_usd
- `tool_execution` records include: tool_name, result_chars, duration_ms, is_error

### Test 6.2: Analyze costs CLI

```bash
python -m micro_x_agent_loop.analyze_costs --file metrics.jsonl
```

**Expected:**
- Prints a summary table matching the `/cost` output
- Shows aggregated totals across all sessions in the file

### Test 6.3: Filter by session

```bash
python -m micro_x_agent_loop.analyze_costs --file metrics.jsonl --session <session_id>
```

(Use a session ID from the REPL — visible in the `/session` command output.)

**Expected:**
- Shows only metrics for that session
- Totals match what `/cost` showed during the session

### Test 6.4: CSV output

```bash
python -m micro_x_agent_loop.analyze_costs --file metrics.jsonl --csv
```

**Expected:**
- Outputs a header row followed by a data row in CSV format
- Importable into a spreadsheet

---

## 7. Edge Cases

### Test 7.1: `/cost` with no API calls yet

Start a fresh session and immediately run `/cost`.

**Expected:**
- Shows all zeroes
- No errors or crashes
- Provider/Model shows "— / —"

### Test 7.2: Very long session

Run 10+ turns with tool calls in a single session.

Run `/cost`.

**Expected:**
- Per-call breakdown lists all calls in order
- Running totals are consistent (sum of per-call costs approximately equals total cost)
- No truncation or formatting issues

### Test 7.3: Session resume preserves accumulator

Start a session, send a few prompts, note the `/cost` output.

Exit the agent, then resume the same session:
```bash
python -m micro_x_agent_loop --session <session_id>
```

Send another prompt, then run `/cost`.

**Expected:**
- Accumulator starts fresh on resume (cost tracks the current run, not historical)
- Only shows API calls made since the agent started
- This is expected behaviour — the accumulator is in-memory, not persisted

---

## Related

- [Manual Test: Cost Reconciliation](MANUAL-TEST-cost-reconciliation.md) — tests for `/cost reconcile` and metrics persistence to SQLite
- [Metrics and Cost Tracking Guide](../operations/metrics-and-costs.md)

---
## Notebook Tests
Automated notebook coverage for selected tests in this plan:
- `notebooks/test_tier1_config_and_logic.ipynb` — Cells 1.1 (pricing lookup), 1.2 (accumulator counters), 1.3 (tool tracking), 1.4 (model subtotals)
- `notebooks/test_tier2_live_api.ipynb` — Cell 2.1 (live accumulator fields)
