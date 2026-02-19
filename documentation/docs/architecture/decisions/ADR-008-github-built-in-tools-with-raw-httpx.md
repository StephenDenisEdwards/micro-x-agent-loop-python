# ADR-008: GitHub as Built-in Tools via Raw httpx

## Status

Accepted

## Context

The agent needed first-class GitHub capabilities (PRs, issues, repository listing, file retrieval, code search) with structured schemas and predictable output formatting.

Two architectural questions were central:

1. Should GitHub be integrated as built-in tools or via MCP/external process?
2. Should the implementation use a higher-level GitHub client library or direct REST calls with `httpx`?

GitHub access in this project is user-scoped and token-based (`GITHUB_TOKEN`), and the existing tool system already supports adding first-party built-in tools with minimal runtime overhead.

## Decision

Implement GitHub as built-in tools in-process, authenticated by `GITHUB_TOKEN`, and use direct REST API calls through a shared async `httpx.AsyncClient`.

Reasons:

- **Consistent with first-party API integrations.** GitHub behaves like other first-party HTTP API tools already implemented in-process.
- **Lower operational complexity.** No additional MCP server process, lifecycle, or transport is required.
- **Explicit API control.** Raw REST calls provide direct control over endpoints, headers, pagination, and error handling.
- **Dependency minimization.** Avoid introducing and pinning a pre-1.0 GitHub SDK for core functionality already covered by stable REST endpoints.

The implementation includes:

- `tools/github/github_auth.py` shared async client with GitHub API base URL and auth headers
- Built-in tools registered from `tool_registry.py` when `GITHUB_TOKEN` is present
- Tool set: list/get PRs, list/create issues, create PR, list repos, get file, search code

## Consequences

**Easier:**

- Structured GitHub operations without shelling out to `gh` or parsing CLI output
- In-process execution with no IPC transport overhead
- Centralized authentication and HTTP behavior in one shared client
- Straightforward extension path for additional GitHub REST endpoints

**Harder:**

- REST request/response modeling is maintained manually in each tool
- Rate-limit behavior must be handled at tool level (not abstracted by an SDK)
- GraphQL and advanced typed API ergonomics are deferred unless needed later
