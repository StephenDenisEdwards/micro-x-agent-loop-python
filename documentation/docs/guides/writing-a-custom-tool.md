# Guide: Writing a Custom Tool

How to design and implement a tool for the micro-x-agent-loop ecosystem.

## Tool Types

| Type | Language | Where | When to Use |
|------|----------|-------|-------------|
| **MCP server tool** | TypeScript | Separate repo | Standard approach for all new tools |
| **Pseudo-tool** | Python | `src/micro_x_agent_loop/` | Agent-internal only (e.g., `ask_user`, `tool_search`) |

**Always prefer MCP server tools.** Pseudo-tools are reserved for agent-internal capabilities that need direct access to the REPL or agent state.

## MCP Server Tool Design

### Tool Protocol

Every MCP tool must provide:
- **Name**: snake_case, descriptive (e.g., `gmail_search`, `web_fetch`)
- **Description**: One sentence explaining what the tool does and when to use it. The LLM reads this to decide whether to call it.
- **Input schema**: Zod schema defining parameters with `.describe()` annotations
- **Output**: Content blocks (usually `type: "text"` with stringified results)

### Input Schema Design

```typescript
server.tool(
  "search_jobs",
  "Search job listings by keyword, location, and filters",
  {
    query: z.string().describe("Search keywords"),
    location: z.string().optional().describe("City or region"),
    remote_only: z.boolean().optional().describe("Filter to remote jobs only"),
    max_results: z.number().optional().default(10).describe("Maximum results to return"),
  },
  async (params) => { /* ... */ }
);
```

Guidelines:
- Use clear parameter names — the LLM infers meaning from them
- Add `.describe()` to every parameter
- Use `.optional()` with sensible defaults where possible
- Prefer simple types (string, number, boolean) over nested objects

### Output Design

Tool results include **human-readable text** for the LLM and optionally **structured data** for programmatic use (see ADR-014). Return both when possible:

```typescript
// Good: clear, parseable text
return {
  content: [{
    type: "text",
    text: `Found 3 jobs:\n\n1. Senior Engineer at Acme (Remote, £85k)\n2. ...`
  }]
};

// Also good: JSON for structured data
return {
  content: [{
    type: "text",
    text: JSON.stringify({ jobs: [...], total: 42 }, null, 2)
  }]
};
```

### Error Handling

Return errors as text content with `isError: true` — do NOT throw or crash:

```typescript
try {
  const result = await fetchData();
  return { content: [{ type: "text", text: result }] };
} catch (error) {
  return {
    content: [{ type: "text", text: `Error: ${error.message}` }],
    isError: true,
  };
}
```

## Pseudo-Tool Design (Python)

Pseudo-tools are Python functions that integrate directly with the agent runtime. Only create these for capabilities that need access to the terminal, message history, or agent state.

### Existing Pseudo-Tools

| Tool | Purpose | File |
|------|---------|------|
| `ask_user` | Pause and ask the user a question | `ask_user.py` |
| `tool_search` | Discover tools from the deferred pool | `tool_search.py` |

### Pattern

1. Define the tool schema as a dict matching the MCP tool schema format
2. Create a handler class with an `async handle(tool_input) -> str` method
3. Register the schema in `TurnEngine` tool conversion
4. Handle the tool call in `TurnEngine._execute_single_tool()`
5. Inject a system prompt directive explaining the tool to the LLM

See `ask_user.py` and the `_ASK_USER_DIRECTIVE` in `system_prompt.py` for the reference implementation.

## Testing

### MCP Server Testing

```bash
# Unit tests within the MCP server project
cd my-mcp-server
npm test

# Integration test: start server, send JSON-RPC, verify response
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | node dist/index.js
```

### Pseudo-Tool Testing

```python
# tests/test_my_tool.py
class MyToolTests(unittest.TestCase):
    def test_basic_execution(self):
        handler = MyToolHandler()
        result = asyncio.run(handler.handle({"param": "value"}))
        self.assertIn("expected", result)
```

## Checklist

- [ ] Tool name is snake_case and descriptive
- [ ] Description is clear and tells the LLM when to use the tool
- [ ] All parameters have `.describe()` annotations
- [ ] Errors are returned as text, not thrown
- [ ] Tool is registered in `config.json` (MCP) or `turn_engine.py` (pseudo-tool)
- [ ] Per-tool documentation added to `documentation/docs/design/tools/`
- [ ] Tests cover happy path and error cases

## Related

- [Tool System Design](../design/DESIGN-tool-system.md)
- [Adding an MCP Server](adding-an-mcp-server.md)
- [ADR-014: Structured Tool Results with Configurable LLM Formatting](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md)
