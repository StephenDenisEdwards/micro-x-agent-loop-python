# Manual Test Plan — Provider-Aware Tool Search + Canonical Tool Serialisation

**Related plan:** [PLAN-cache-preserving-tool-routing.md](../planning/PLAN-cache-preserving-tool-routing.md) — Phase 1
**Code under test:** `src/micro_x_agent_loop/tool.py` (`canonicalise_tools`), `src/micro_x_agent_loop/tool_search.py` (`should_activate_tool_search`), provider modules (`anthropic_provider.py`, `openai_provider.py`, `gemini_provider.py`, `deepseek_provider.py`)

---

## Prerequisites

- Anthropic API key configured in `.env`
- `config-base.json` accessible (default `ToolSearchEnabled: "auto"`)
- Log level `DEBUG` to observe tool search activation and cache behaviour

---

## Test 1 — Auto + Anthropic: tool search inactive

**Goal:** Verify that with `ToolSearchEnabled: "auto"` and Anthropic provider, tool search is disabled to preserve the prompt cache.

**Steps:**

1. Ensure config:
   ```json
   {
     "Provider": "anthropic",
     "ToolSearchEnabled": "auto",
     "PromptCachingEnabled": true
   }
   ```
2. Start the agent: `python -m micro_x_agent_loop`
3. Check startup logs

**Expected:**
- Log shows: `Tool search: auto + anthropic provider — inactive (cache-preserving, >=90% discount)`
- No `tool_search` pseudo-tool in the tool list (all real tools sent directly)
- On turn 2+, `cache_read_input_tokens > 0` in debug logs (cache hit)

---

## Test 2 — Auto + OpenAI: tool search applies threshold

**Goal:** Verify that with `ToolSearchEnabled: "auto"` and OpenAI provider, tool search activates based on token threshold.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "openai",
     "Model": "gpt-4o",
     "ToolSearchEnabled": "auto"
   }
   ```
2. Start the agent
3. Check startup logs

**Expected:**
- Log shows tool token count vs threshold: `Tool search: N tool tokens vs M threshold (40% of 128000)`
- If tool tokens exceed threshold → `ACTIVE`, tool_search pseudo-tool available
- If tool tokens below threshold → `inactive`, all tools sent directly

---

## Test 3 — Explicit "true" overrides Anthropic

**Goal:** Verify that `ToolSearchEnabled: "true"` forces tool search on regardless of provider.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "anthropic",
     "ToolSearchEnabled": "true"
   }
   ```
2. Start the agent
3. Submit: "what tools do you have?"

**Expected:**
- Log shows: `Tool search active: N tools deferred`
- LLM only sees `tool_search` pseudo-tool initially
- LLM calls `tool_search` to discover tools before using them

---

## Test 4 — Explicit "false" overrides OpenAI

**Goal:** Verify that `ToolSearchEnabled: "false"` disables tool search regardless of provider.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "openai",
     "ToolSearchEnabled": "false"
   }
   ```
2. Start the agent

**Expected:**
- All tools sent directly to the LLM
- No tool_search pseudo-tool
- No "Tool search" log messages (aside from the setting evaluation)

---

## Test 5 — Canonical tool ordering: cache stability across restarts

**Goal:** Verify that tool ordering is deterministic regardless of MCP server startup order.

**Steps:**

1. Use default config (`Provider: "anthropic"`, `PromptCachingEnabled: true`)
2. Start the agent with `LogLevel: "DEBUG"`
3. Submit a prompt, note the `tools=N` count in the API request log
4. Submit a second prompt
5. Check `cache_read_input_tokens` on turn 2
6. Stop the agent
7. Restart the agent (MCP servers restart in potentially different order)
8. Submit two prompts again
9. Compare tool schemas between sessions

**Expected:**
- Turn 2 shows `cache_read_input_tokens > 0` (cache hit — tools haven't changed)
- After restart, tool ordering is identical (same alphabetical order)
- No "Tool schema changed" warnings in logs

---

## Test 6 — Auto with custom threshold

**Goal:** Verify that `ToolSearchEnabled: "auto:N"` overrides the default threshold percentage.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "openai",
     "ToolSearchEnabled": "auto:0"
   }
   ```
2. Start the agent

**Expected:**
- With threshold 0%, any tools should activate tool search
- Log shows: `Tool search: N tool tokens vs 0 threshold (0% of 128000) — ACTIVE`

---

## Test 7 — Auto:0 still respects Anthropic override

**Goal:** Verify that even with `auto:0` (threshold 0%), Anthropic provider still disables tool search.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "anthropic",
     "ToolSearchEnabled": "auto:0"
   }
   ```
2. Start the agent

**Expected:**
- Log shows: `Tool search: auto + anthropic provider — inactive (cache-preserving, >=90% discount)`
- Tool search NOT activated despite 0% threshold
- All tools sent to the LLM directly

---

## Test 8 — Auto + Gemini: tool search inactive (cache-preserving)

**Goal:** Verify that with `ToolSearchEnabled: "auto"` and Gemini provider, tool search is disabled (Gemini has 90% cache discount, no write surcharge, automatic implicit caching).

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "gemini",
     "Model": "gemini-2.5-flash",
     "ToolSearchEnabled": "auto"
   }
   ```
2. Start the agent
3. Check startup logs

**Expected:**
- Log shows: `Tool search: auto + gemini provider — inactive (cache-preserving, >=90% discount)`
- No `tool_search` pseudo-tool in the tool list
- All real tools sent directly to the LLM

---

## Test 9 — Auto + DeepSeek: tool search inactive (cache-preserving)

**Goal:** Verify that with `ToolSearchEnabled: "auto"` and DeepSeek provider, tool search is disabled (DeepSeek has 90% cache discount, no write surcharge, fully automatic caching).

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "deepseek",
     "Model": "deepseek-chat",
     "ToolSearchEnabled": "auto"
   }
   ```
2. Start the agent
3. Check startup logs

**Expected:**
- Log shows: `Tool search: auto + deepseek provider — inactive (cache-preserving, >=90% discount)`
- No `tool_search` pseudo-tool in the tool list
- All real tools sent directly to the LLM

---

## Test 10 — Auto:0 still respects Gemini override

**Goal:** Verify that even with `auto:0` (threshold 0%), Gemini provider still disables tool search.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "gemini",
     "Model": "gemini-2.5-flash",
     "ToolSearchEnabled": "auto:0"
   }
   ```
2. Start the agent

**Expected:**
- Log shows: `Tool search: auto + gemini provider — inactive (cache-preserving, >=90% discount)`
- Tool search NOT activated despite 0% threshold

---

## Test 11 — Auto:0 still respects DeepSeek override

**Goal:** Verify that even with `auto:0` (threshold 0%), DeepSeek provider still disables tool search.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "deepseek",
     "Model": "deepseek-chat",
     "ToolSearchEnabled": "auto:0"
   }
   ```
2. Start the agent

**Expected:**
- Log shows: `Tool search: auto + deepseek provider — inactive (cache-preserving, >=90% discount)`
- Tool search NOT activated despite 0% threshold

---

## Test 12 — Explicit "true" overrides Gemini and DeepSeek

**Goal:** Verify that `ToolSearchEnabled: "true"` forces tool search on for cache-preserving providers.

**Steps:**

1. Configure with Gemini:
   ```json
   {
     "Provider": "gemini",
     "Model": "gemini-2.5-flash",
     "ToolSearchEnabled": "true"
   }
   ```
2. Start the agent, verify tool_search pseudo-tool is active
3. Repeat with DeepSeek:
   ```json
   {
     "Provider": "deepseek",
     "Model": "deepseek-chat",
     "ToolSearchEnabled": "true"
   }
   ```
4. Start the agent, verify tool_search pseudo-tool is active

**Expected:**
- Both providers show tool search active despite being cache-preserving providers
- LLM sees `tool_search` pseudo-tool

---

## Test 13 — Tool search works end-to-end on OpenAI (unchanged)

**Goal:** Verify that when tool search is active on OpenAI, the LLM can discover and use tools.

**Steps:**

1. Configure:
   ```json
   {
     "Provider": "openai",
     "Model": "gpt-4o",
     "ToolSearchEnabled": "true"
   }
   ```
2. Start the agent
3. Submit: "read the file config.json"
4. Observe the LLM's behaviour

**Expected:**
- LLM first calls `tool_search` with a query like "read file"
- Tool search returns matching file tools
- LLM then calls the discovered `filesystem__read_file` tool
- File contents returned successfully
- `/cost` shows multiple API calls (search + tool call + response)
