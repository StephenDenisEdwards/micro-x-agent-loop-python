# Sub-Agents — Manual Test Plan

Step-by-step walkthrough of every sub-agent feature (Phase 1 + Phase 2a routing policy). Run these from the project root directory using the interactive REPL.

> **Prerequisites**
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - A working `config.json` with at least one LLM provider configured
> - `.env` with valid API keys
> - At least one MCP server with read-only tools (e.g., `filesystem`) available
> - `SubAgentsEnabled` set to `true` in your config (see section 1)

> **Cost awareness**
> Sub-agent tests make real LLM API calls. Explore/summarize types use the cheaper sub-agent model; general uses the parent model. Budget approximately $0.10–$0.50 for a full test run depending on models configured.

---

## 1. Configuration

### Test 1.1: Enable sub-agents (minimal config)

Add the following to your `config.json` (or the file it points to via `ConfigFile`):

```json
{
  "SubAgentsEnabled": true
}
```

Start the agent:
```bash
python -m micro_x_agent_loop
```

**Expected:**
- Agent starts normally with no errors
- The system prompt includes the sub-agent delegation section (not directly visible, but the LLM will have access to `spawn_subagent`)

### Test 1.2: Configure a cheaper sub-agent model

```json
{
  "SubAgentsEnabled": true,
  "SubAgentModel": "claude-haiku-4-5-20251001"
}
```

**Expected:** Agent starts normally. Explore and summarize sub-agents will use Haiku instead of the parent model.

### Test 1.3: Configure custom limits

```json
{
  "SubAgentsEnabled": true,
  "SubAgentModel": "claude-haiku-4-5-20251001",
  "SubAgentTimeout": 60,
  "SubAgentMaxTurns": 10,
  "SubAgentMaxTokens": 2048
}
```

**Expected:** Agent starts normally. Sub-agents will use the tighter limits.

### Test 1.4: Sub-agents disabled (default)

Ensure `SubAgentsEnabled` is `false` or absent in config.

```bash
python -m micro_x_agent_loop
```

**Expected:** Agent starts normally. The `spawn_subagent` tool is **not** available to the LLM — prompts that would benefit from delegation are handled directly by the parent agent instead.

---

## 2. Explore Sub-Agent (Read-Only Research)

Start the agent with sub-agents enabled (test 1.2 config recommended).

### Test 2.1: File search and summary

```
you> Use a sub-agent to find all Python files in the src/ directory that import asyncio, and summarize what each one uses it for.
```

**Expected:**
- The agent calls `spawn_subagent` with type `explore`
- Terminal shows a tool execution indicator for `spawn_subagent`
- After a few seconds, the agent receives a concise summary from the sub-agent
- The agent presents the findings — a list of files with brief descriptions
- The `/cost` command shows sub-agent token usage (look for `subagent:explore` in the breakdown)

### Test 2.2: Multi-file code exploration

```
you> Spawn an explore sub-agent to find out how error handling works in the turn engine — look at exception types, retry logic, and how errors are reported to the user.
```

**Expected:**
- Sub-agent reads multiple files (`turn_engine.py`, possibly `agent.py`, `agent_channel.py`)
- Returns a structured summary of the error handling approach
- Parent agent presents the findings coherently
- Only read-only tools are used (no file modifications)

### Test 2.3: Explore with web tools (if available)

If you have `web_fetch` or `web_search` MCP tools configured:

```
you> Use a sub-agent to research the latest version of the anthropic Python SDK on PyPI and what changed in the most recent release.
```

**Expected:**
- Sub-agent uses web tools to fetch information
- Returns a concise summary of version and changelog
- Parent agent presents the results

### Test 2.4: Explore sub-agent cannot write files

```
you> Spawn an explore sub-agent to create a new file called /tmp/test-subagent.txt with the text "hello world".
```

**Expected:**
- The sub-agent should **not** have access to write tools
- The agent either reports that the sub-agent couldn't perform the write, or the sub-agent's summary indicates it lacks write capability
- No file is created

---

## 3. Summarize Sub-Agent (No Tools)

### Test 3.1: Summarize inline content

```
you> Use a summarize sub-agent to distill this into 3 bullet points: [paste a long paragraph or article text, 500+ words]
```

**Expected:**
- The agent calls `spawn_subagent` with type `summarize`
- The sub-agent has **no tools** — it operates purely on the task text
- Returns a concise 3-bullet summary
- Completes quickly (single turn, no tool calls)

### Test 3.2: Summarize with tool request (should be ignored)

```
you> Spawn a summarize sub-agent to read the file pyproject.toml and summarize it.
```

**Expected:**
- The summarize sub-agent has no tools, so it **cannot** read the file
- The sub-agent either explains it can't access files, or the parent agent recognizes this and uses explore type instead
- This tests that the LLM learns to pick the right agent type

---

## 4. General Sub-Agent (Full Capability)

### Test 4.1: General sub-agent with write tools

```
you> Use a general sub-agent to read pyproject.toml and tell me the project version.
```

**Expected:**
- The agent calls `spawn_subagent` with type `general`
- The sub-agent has access to all parent tools (including write tools)
- Returns the version string from pyproject.toml
- Uses the **parent model** (not the cheaper sub-agent model)

### Test 4.2: Verify general uses parent model

After running test 4.1, check costs:

```
you> /cost
```

**Expected:**
- The `subagent:general` usage shows the parent model name, not the sub-agent model
- Token costs reflect the parent model's pricing

---

## 5. Concurrent Sub-Agents

### Test 5.1: Multiple sub-agents in parallel

```
you> I need three things researched in parallel using sub-agents:
1. What Python version is required in pyproject.toml?
2. How many test files are in the tests/ directory?
3. What MCP servers are configured in config.json?
```

**Expected:**
- The agent calls `spawn_subagent` multiple times in a single response
- All sub-agents execute **concurrently** (you should see them start at roughly the same time)
- Results return and are presented together
- Total wall-clock time is close to the slowest sub-agent, not the sum of all three

### Test 5.2: Mixed sub-agent types in parallel

```
you> Do these in parallel:
1. (explore) Find all files that mention "SubAgentRunner" in the src/ directory
2. (summarize) Summarize this text in one sentence: "The quick brown fox jumps over the lazy dog. This sentence contains every letter of the English alphabet and has been used as a typing test since at least the late 19th century."
```

**Expected:**
- Both sub-agents run concurrently
- Explore sub-agent uses tools to search files
- Summarize sub-agent works with no tools
- Both results are presented

---

## 6. Timeout and Error Handling

### Test 6.1: Sub-agent timeout

Set a very short timeout in config:

```json
{
  "SubAgentsEnabled": true,
  "SubAgentTimeout": 5
}
```

Then give a task that requires multiple tool calls:

```
you> Use a sub-agent to read every Python file in src/micro_x_agent_loop/ and count the total number of lines across all files.
```

**Expected:**
- The sub-agent times out after 5 seconds
- The parent agent receives a result indicating timeout
- The parent agent handles it gracefully (may report partial results or explain the timeout)
- No crash or hang

### Test 6.2: Sub-agent with unavailable tools

If you have MCP servers that are stopped/unavailable:

```
you> Use a sub-agent to search the web for "Python 3.13 release date".
```

(When no web tools are available)

**Expected:**
- The sub-agent either reports it has no web tools, or the parent agent explains the limitation
- No crash or unhandled error

### Test 6.3: Sub-agent with invalid type (LLM edge case)

This tests robustness — the LLM might pass an invalid type. Not directly triggerable via prompt, but verify via unit tests (`tests/test_sub_agent.py`):

```bash
python -m pytest tests/test_sub_agent.py -v
```

**Expected:** All 33 tests pass, including the edge case where an invalid type defaults to `explore`.

---

## 7. Context Window Protection

This is the core value proposition of sub-agents — verify that large research doesn't bloat the parent context.

### Test 7.1: Large exploration stays compact

```
you> Use a sub-agent to read all the ADR files in documentation/docs/architecture/ and give me a one-line summary of each.
```

**Expected:**
- The sub-agent reads many files (potentially 18+ ADRs)
- The parent context receives only the **summary** (not the raw file contents)
- You can continue the conversation with the parent agent without hitting context limits
- Compare: doing this without sub-agents would consume significant context with raw file content

### Test 7.2: Follow-up after sub-agent research

After test 7.1, continue the conversation:

```
you> Based on those ADRs, which ones are related to tool handling?
```

**Expected:**
- The parent agent can answer based on the sub-agent's summary
- The conversation remains responsive (no context pressure)

---

## 8. Cost Tracking

### Test 8.1: Sub-agent costs appear in /cost

Run any sub-agent test, then:

```
you> /cost
```

**Expected:**
- Cost breakdown includes `subagent:explore`, `subagent:summarize`, or `subagent:general` entries
- Token counts (input/output) are tracked per sub-agent call
- Sub-agent costs are aggregated into the session total

### Test 8.2: Cheap explore vs expensive general

Run an explore task and a general task with the same prompt, then compare costs:

```
you> Use an explore sub-agent to read pyproject.toml and tell me the project name.
you> Use a general sub-agent to read pyproject.toml and tell me the project name.
you> /cost
```

**Expected:**
- The explore call uses the cheaper sub-agent model (if configured)
- The general call uses the parent model
- Cost difference is visible in the breakdown

---

## 9. Nesting Boundary

### Test 9.1: Sub-agents cannot spawn sub-agents

```
you> Use a sub-agent to spawn another sub-agent to read pyproject.toml.
```

**Expected:**
- The sub-agent does **not** have access to `spawn_subagent` (Phase 1: 1-level nesting only)
- The sub-agent either reads the file directly (if explore/general type) or reports it cannot delegate
- No recursive sub-agent spawning occurs

---

## 10. Integration with Other Features

### Test 10.1: Sub-agents with session persistence

If `MemoryEnabled=true`:

```
you> Use a sub-agent to find the project version in pyproject.toml.
```

Then restart the agent with the same session:

```bash
python -m micro_x_agent_loop --session <same-session-id>
```

```
you> What version did we find earlier?
```

**Expected:**
- The sub-agent result (summary) is part of the message history
- After session restore, the parent agent can recall the sub-agent's findings
- Note: the sub-agent's internal messages are **not** persisted — only its final summary in the parent's tool result

### Test 10.2: Sub-agents via API server

Start the server with sub-agents enabled:

```bash
python -m micro_x_agent_loop --server start
```

```bash
curl -X POST http://127.0.0.1:8321/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Use a sub-agent to find out what Python version is required in pyproject.toml.\"}"
```

**Expected:**
- The REST response includes the sub-agent's findings
- No errors related to sub-agent execution in server mode

### Test 10.3: Sub-agents via WebSocket

```bash
websocat ws://127.0.0.1:8321/api/ws/subagent-test
```

Send:
```json
{"type": "message", "text": "Use an explore sub-agent to list the files in the tests/ directory."}
```

**Expected events:**
1. `{"type": "tool_started", "tool": "spawn_subagent", ...}` — sub-agent begins
2. `{"type": "tool_completed", "tool": "spawn_subagent", "error": false, ...}` — sub-agent finishes
3. `{"type": "text_delta", ...}` — parent streams response using sub-agent results
4. `{"type": "turn_complete", ...}` — includes aggregated usage

---

## 11. Routing Policy (Phase 2a)

These tests verify the enhanced routing directive — the LLM should **actively prefer** sub-agents for exploratory work without being explicitly asked.

### Test 11.1: Implicit delegation for multi-file search

Do **not** mention sub-agents in the prompt:

```
you> How does error handling work across the codebase? Look at the providers, turn engine, and agent modules.
```

**Expected:**
- The agent should autonomously spawn an explore sub-agent to read multiple files
- The agent should NOT read all files directly in its own context
- The response should present a coherent summary from the sub-agent's findings

### Test 11.2: Implicit delegation for web research

```
you> What are the current pricing tiers for the Anthropic API?
```

**Expected:**
- The agent should spawn an explore sub-agent to do the web research
- The sub-agent handles the web_search/web_fetch calls
- Only the summary returns to the parent context

### Test 11.3: Direct tool use for simple operations

```
you> Read config-base.json and tell me what model is configured.
```

**Expected:**
- The agent should **NOT** spawn a sub-agent for this — it's a single file read
- The agent reads the file directly in its own context
- This verifies the "Do NOT delegate" rules are working

### Test 11.4: Parallel delegation without explicit instruction

```
you> I need to understand both the compaction system and the metrics system. How do they work?
```

**Expected:**
- The agent may spawn 2 explore sub-agents concurrently (one for compaction, one for metrics)
- Or it may spawn one sub-agent for both topics — either is acceptable
- The key test: the agent should prefer delegation over reading many files directly

### Test 11.5: Default-enabled with no explicit config

Start the agent with the default `config-base.json` (which now has `SubAgentsEnabled: true`):

```bash
python -m micro_x_agent_loop
```

```
you> Search the tests directory for all test classes related to cost reduction and list them.
```

**Expected:**
- Sub-agents work out of the box with no user configuration
- The `spawn_subagent` tool is available and used for this multi-file search task

---

## Cleanup

Reset your config to the desired production settings (e.g., remove short timeout overrides from test 6.1).

---

## Test Summary Checklist

| # | Feature | Status |
|---|---------|--------|
| 1.1 | Enable sub-agents (minimal) | |
| 1.2 | Cheaper sub-agent model | |
| 1.3 | Custom limits | |
| 1.4 | Sub-agents disabled | |
| 2.1 | Explore: file search | |
| 2.2 | Explore: multi-file code exploration | |
| 2.3 | Explore: web tools | |
| 2.4 | Explore: cannot write files | |
| 3.1 | Summarize: inline content | |
| 3.2 | Summarize: no tools available | |
| 4.1 | General: full capability | |
| 4.2 | General: uses parent model | |
| 5.1 | Concurrent: multiple in parallel | |
| 5.2 | Concurrent: mixed types | |
| 6.1 | Timeout handling | |
| 6.2 | Unavailable tools | |
| 6.3 | Unit tests pass | |
| 7.1 | Context protection: large exploration | |
| 7.2 | Context protection: follow-up | |
| 8.1 | Cost tracking in /cost | |
| 8.2 | Cheap vs expensive model comparison | |
| 9.1 | No nested sub-agents | |
| 10.1 | Session persistence | |
| 10.2 | API server (REST) | |
| 10.3 | API server (WebSocket) | |
| 11.1 | Routing: implicit delegation for multi-file search | |
| 11.2 | Routing: implicit delegation for web research | |
| 11.3 | Routing: direct tool use for simple ops | |
| 11.4 | Routing: parallel delegation without instruction | |
| 11.5 | Routing: default-enabled with no config | |
