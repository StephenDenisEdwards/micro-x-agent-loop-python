# @micro-x/mcp-echo

A minimal MCP server that echoes back messages. Useful for testing MCP client connectivity and verifying your setup works end-to-end.

## Install and run

```bash
npx -y @micro-x/mcp-echo
```

No environment variables or authentication required.

## Tools

| Tool | Description |
|------|-------------|
| `echo` | Echo back the provided message with a timestamp |

### Example

**Input:** `{ "message": "hello world" }`
**Output:** `{ "echoed": "hello world", "timestamp": "2026-04-29T12:00:00.000Z" }`

## Client configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "echo": {
      "command": "npx",
      "args": ["-y", "@micro-x/mcp-echo"]
    }
  }
}
```

### Claude Code

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "echo": {
      "command": "npx",
      "args": ["-y", "@micro-x/mcp-echo"]
    }
  }
}
```

### micro-x agent loop

Add to `config.json` under `McpServers`:

```json
{
  "McpServers": {
    "echo": {
      "Command": "npx",
      "Args": ["-y", "@micro-x/mcp-echo"]
    }
  }
}
```

## Flags

| Flag | Description |
|------|-------------|
| `--help`, `-h` | Print usage information and exit |

## License

MIT
