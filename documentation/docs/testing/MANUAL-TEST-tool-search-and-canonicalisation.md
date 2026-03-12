# Manual Test Plan — Provider-Aware Tool Search + Canonical Tool Serialisation

**Related plan:** [PLAN-cache-preserving-tool-routing.md](../planning/PLAN-cache-preserving-tool-routing.md) — Phase 1
**Code under test:** `src/micro_x_agent_loop/tool.py` (`canonicalise_tools`), `src/micro_x_agent_loop/tool_search.py` (`should_activate_tool_search`), `src/micro_x_agent_loop/providers/anthropic_provider.py`, `src/micro_x_agent_loop/providers/openai_provider.py`

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
- Log shows: `Tool search: auto + Anthropic provider — inactive (cache-preserving)`
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
- Log shows: `Tool search: auto + Anthropic provider — inactive (cache-preserving)`
- Tool search NOT activated despite 0% threshold
- All tools sent to the LLM directly

---

## Test 8 — Tool search works end-to-end on OpenAI

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
