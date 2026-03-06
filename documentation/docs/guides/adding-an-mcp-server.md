# Guide: Adding an MCP Server

How to add a new tool to the agent by creating and registering an MCP server.

## Overview

All tools in micro-x-agent-loop are MCP (Model Context Protocol) servers. The agent discovers tools automatically via the MCP protocol at startup. You do NOT write Python tool code — you create a TypeScript MCP server in a separate repository and register it in `config.json`.

## Step-by-Step

### 1. Create the MCP Server

MCP servers are TypeScript projects using the `@modelcontextprotocol/sdk` package. A minimal server exposes one or more tools:

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({
  name: "my-tool-server",
  version: "1.0.0",
});

server.tool(
  "my_tool",
  "Description of what this tool does",
  {
    query: z.string().describe("The search query"),
  },
  async ({ query }) => {
    const result = await doSomething(query);
    return {
      content: [{ type: "text", text: JSON.stringify(result) }],
    };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
```

### 2. Build and Test Locally

```bash
cd my-mcp-server
npm install
npm run build
# Test: should start and accept JSON-RPC over stdio
node dist/index.js
```

### 3. Register in config.json

Add your server to the `McpServers` section of `config.json`:

```json
{
  "McpServers": {
    "my-tool-server": {
      "command": "node",
      "args": ["path/to/my-mcp-server/dist/index.js"],
      "env": {
        "MY_API_KEY": "${MY_API_KEY}"
      }
    }
  }
}
```

Key fields:
- **`command`**: The executable to run (usually `node`)
- **`args`**: Arguments passed to the command
- **`env`**: Environment variables — use `${VAR}` syntax for secrets from `.env`

### 4. Add Secrets to .env

If your server needs API keys:

```
MY_API_KEY=sk-...
```

### 5. Verify at Startup

Start the agent. Your tools should appear in the startup tool listing:

```
Tools loaded:
  ...
  [my-tool-server] my_tool — Description of what this tool does
```

Use `/tools mcp` to see tools grouped by server.

## Best Practices

See [MCP Server Best Practices](../best-practice/mcp-servers.md) for detailed guidance.

Key points:
- Return unstructured text in tool results (the LLM interprets it)
- Handle errors gracefully — return error text, don't crash the server
- Keep tool descriptions clear and concise — the LLM uses them to decide when to call the tool
- Use `structuredContent` for rich metadata when appropriate
- Add retry/resilience for external API calls (ADR-016)

## Tool Documentation

Create a per-tool doc in `documentation/docs/design/tools/your-tool/README.md` following the existing pattern. Include:
- Tool name and description
- Parameters with types and descriptions
- Example input/output
- Related ADRs or design decisions

## Related

- [ADR-005: MCP for External Tools](../architecture/decisions/ADR-005-mcp-external-tools.md)
- [ADR-006: Separate Repos for Third-Party MCP Servers](../architecture/decisions/ADR-006-separate-repos-for-third-party-mcp-servers.md)
- [ADR-016: Retry/Resilience for MCP Servers](../architecture/decisions/ADR-016-retry-resilience-mcp-servers.md)
- [Tool System Design](../design/DESIGN-tool-system.md)
