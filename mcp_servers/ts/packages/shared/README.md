# @micro-x/mcp-shared

Internal shared utilities for [`@micro-x/mcp-*`](https://github.com/StephenDenisEdwards/micro-x-agent-loop-python/tree/master/mcp_servers/ts/packages) servers.

Provides logging, input/output validation, retry-aware HTTP fetch, Zod-to-JSON-Schema conversion, and a server factory for stdio-based MCP servers.

**This package is not intended for direct consumption.** It is a dependency of the individual `@micro-x/mcp-*` server packages. You should install those instead.

## Exported modules

| Module | Purpose |
|--------|---------|
| `createLogger` | Pino logger writing to stderr (stdout reserved for JSON-RPC) |
| `createServer` / `startStdioServer` | MCP server factory with graceful shutdown |
| `validateInput` / `validateOutput` | Zod-based input/output validation |
| `resilientFetch` | Fetch with exponential backoff, transient-error retry, rate-limit awareness |
| `createToolHandler` | Standard tool wrapper with logging, timing, and error categorisation |
| `ResultSchema` / `PaginationSchema` / `zodToJsonSchema` | Reusable schemas |
| `ValidationError` / `UpstreamError` / `PermissionError` | Typed error classes |

## License

MIT
