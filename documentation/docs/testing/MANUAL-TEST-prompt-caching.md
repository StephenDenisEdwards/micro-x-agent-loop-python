# Manual Test Plan — Strategy 1: Prompt Caching

**Related review:** [cost-reduction-review.md](../review/cost-reduction-review.md) — Strategy 1
**Code under test:** `src/micro_x_agent_loop/providers/anthropic_provider.py` lines 59–75

---

## Prerequisites

- Anthropic API key configured in `.env`
- Config profile with `PromptCachingEnabled: true` (default)
- `metrics.jsonl` output enabled (default)
- At least one MCP tool server configured

---

## Test 1 — Cache headers applied to API requests

**Goal:** Verify that `cache_control: {"type": "ephemeral"}` is present on the system prompt and last tool definition.

**Steps:**

1. Set log level to `DEBUG` in config or via `LOG_LEVEL=DEBUG`
2. Start the agent: `python -m micro_x_agent_loop`
3. Send a simple prompt: `hello`
4. Check debug logs for the API request payload

**Expected:**
- System prompt is sent as a list with a single block containing `cache_control: {"type": "ephemeral"}`
- The last tool in the tools array has `cache_control: {"type": "ephemeral"}`
- Log line includes `prompt_caching=True`

---

## Test 2 — Cache read tokens reported on subsequent turns

**Goal:** Verify the API returns `cache_read_input_tokens > 0` on turns after the first.

**Steps:**

1. Start the agent with default config (`PromptCachingEnabled: true`)
2. Send a first prompt: `what tools do you have?`
3. Send a second prompt: `list them again`
4. Run `/cost` to display session metrics, or inspect `metrics.jsonl`

**Expected:**
- Turn 1: `cache_creation_input_tokens > 0`, `cache_read_input_tokens = 0`
- Turn 2: `cache_read_input_tokens > 0` (system prompt + tools served from cache)
- Turn 2 input cost is lower than Turn 1 for comparable message sizes

---

## Test 3 — Caching disabled via config

**Goal:** Verify that setting `PromptCachingEnabled: false` sends plain system prompt with no cache headers.

**Steps:**

1. Set `PromptCachingEnabled: false` in config
2. Start the agent and send a prompt
3. Check debug logs for the API request payload

**Expected:**
- System prompt is sent as a plain string (not a list)
- No tool definitions contain `cache_control`
- Log line includes `prompt_caching=False`
- `cache_creation_input_tokens = 0` and `cache_read_input_tokens = 0` in metrics

---

## Test 4 — No tools configured (edge case)

**Goal:** Verify caching works without errors when no MCP tools are available.

**Steps:**

1. Remove or comment out all MCP server configs
2. Set `PromptCachingEnabled: true`
3. Start the agent and send a prompt

**Expected:**
- No error on startup or API call
- System prompt still has `cache_control` applied
- Empty tools array is sent without crash

---

## Test 5 — Cost savings visible across a short session

**Goal:** Validate the documented 82% savings claim for a 4-call session.

**Steps:**

1. Start a fresh session with default config
2. Execute 4 turns with simple prompts (e.g., ask about tools, ask a question, ask a follow-up, ask to summarise)
3. Run `/cost` or inspect `metrics.jsonl`
4. Compare total input token cost against what it would be without caching (all tokens at full input price)

**Expected:**
- Cache read tokens grow with each turn
- Total input cost is materially lower than `input_tokens × full_input_price`
- Reference: [prompt-caching-cost-analysis.md](../operations/prompt-caching-cost-analysis.md)
