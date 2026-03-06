# Guide: Debugging Tool Failures

Common patterns for diagnosing and fixing tool execution problems.

## Quick Diagnosis

### 1. Check Tool Availability

```
you> /tools
```

If your tool doesn't appear, check:
- Is the MCP server registered in `config.json` under `McpServers`?
- Does the server binary exist at the configured path?
- Can you run the server manually? (`node path/to/dist/index.js`)

### 2. Check MCP Server Logs

MCP servers log to stderr. Look for startup errors:

```bash
# Run the server directly to see errors
node mcp_servers/ts/my-server/dist/index.js
```

Common startup failures:
- Missing environment variables (API keys not in `.env`)
- Port conflicts
- Missing `node_modules` (run `npm install` in the server directory)

### 3. Enable Debug Logging

Set `LogLevel` to `DEBUG` in `config.json`:

```json
{
  "LogLevel": "DEBUG"
}
```

Or use the `/debug` command during a session to see detailed tool execution info.

## Common Issues

### Tool Returns Empty Result

**Symptom:** Tool executes but the LLM gets no useful content.

**Causes:**
- The external API returned empty data
- The tool's response formatting drops content
- The tool result exceeds `MaxToolResultChars` and is truncated

**Fix:** Check `MaxToolResultChars` in config (default: 50,000). Increase if tools return large results. Check the tool's server code for response formatting issues.

### Tool Timeout

**Symptom:** Tool hangs and eventually fails.

**Causes:**
- External API is slow or unresponsive
- MCP server doesn't implement timeout handling

**Fix:** Add timeout handling in the MCP server. The agent has retry/resilience for MCP transport (ADR-016), but individual tool calls need their own timeouts.

### Tool Returns Error

**Symptom:** LLM sees an error message and tries to recover.

**Causes:**
- Authentication failure (expired token, missing API key)
- Rate limiting from external API
- Invalid parameters from the LLM

**Fix:** Check the error text in the agent output. Common patterns:
- `401/403` → Check API keys in `.env`
- `429` → Rate limited; the agent will retry automatically via tenacity
- `Invalid parameter` → The tool description may be unclear; improve it so the LLM sends correct parameters

### MCP Server Crashes

**Symptom:** Tool call fails with a transport error.

**Causes:**
- Unhandled exception in the MCP server
- Server process exited unexpectedly

**Fix:** Run the server standalone and reproduce the failing input. Add error handling in the tool implementation — return error text instead of throwing.

### Tool Result Summarization Issues

**Symptom:** Tool result is summarised and loses important details.

**Causes:**
- `ToolResultSummarizationEnabled=true` and the result exceeds `ToolResultSummarizationThreshold`
- The summarization model drops key data

**Fix:** Use `config-standard-no-summarization.json` (recommended profile). ADR-013 documents why tool result summarization is unreliable.

### Gmail OAuth Errors

**Symptom:** Gmail tools fail with authentication errors.

**Causes:**
- OAuth tokens expired
- Missing or incorrect `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`
- `credentials.json` not generated

**Fix:** See [Troubleshooting](../operations/troubleshooting.md) for the full Gmail OAuth setup flow.

## Debugging Workflow

### Step 1: Reproduce

Run the exact same prompt and observe the tool output in the terminal.

### Step 2: Isolate

- Is it the MCP server? → Run it standalone
- Is it the external API? → Call the API directly
- Is it the agent? → Check message history with `/debug`

### Step 3: Check the Chain

```
User prompt → LLM decides to call tool → Agent dispatches to MCP server
→ MCP server calls external API → Result flows back → LLM interprets result
```

Failures can occur at any step. The agent output shows:
- Which tool was called and with what parameters
- Whether the result was an error
- Whether the result was truncated or summarised

### Step 4: Fix and Verify

- MCP server bug → Fix in the server repo, rebuild, restart agent
- Config issue → Fix in `config.json` or `.env`, restart agent
- Agent bug → Fix in `src/micro_x_agent_loop/`, run tests

## Metrics

If `MetricsEnabled=true`, tool execution data is written to `metrics.jsonl`:

```json
{
  "type": "tool_execution",
  "tool_name": "gmail_search",
  "result_chars": 12450,
  "duration_ms": 1230.5,
  "is_error": false,
  "was_summarized": false
}
```

Use this to identify slow or failing tools over time.

## Related

- [Troubleshooting](../operations/troubleshooting.md)
- [Configuration Reference](../operations/config.md)
- [Tool System Design](../design/DESIGN-tool-system.md)
- [ADR-013: Tool Result Summarization is Unreliable](../architecture/decisions/ADR-013-tool-result-summarization-unreliable.md)
