# ADR-006: Separate Repos for Third-Party MCP Servers

## Status

Accepted

## Context

The agent connects to multiple MCP servers configured in `config.json`. Some of these servers are **first-party** (developed and maintained alongside the agent, such as the system-info server in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo), while others are **third-party** (maintained by external developers, such as [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)).

The question arose whether third-party MCP servers should be included in the `mcp-servers` monorepo to simplify dependency management and provide a single location for all MCP server code.

Options considered:

1. **Git submodule** — add the third-party repo as a submodule in `mcp-servers`. Tracks a specific commit; updated explicitly.
2. **Git subtree** — merge the third-party repo's files directly into `mcp-servers`. History is flattened; updates require `git subtree pull`.
3. **Copy files** — copy the third-party source code into `mcp-servers` and maintain it as our own fork.
4. **Keep separate repos** — leave third-party MCP servers in their own repositories. The agent references them by absolute path in `config.json`.

## Decision

Keep third-party MCP servers in separate repositories. Each server is cloned, built, and configured independently. The agent's `config.json` references each server by its absolute filesystem path.

Reasons:

- **Different ownership.** Third-party servers are maintained by external developers. Including them creates ambiguity about who is responsible for updates, bug fixes, and security patches.
- **Different build toolchains.** The WhatsApp MCP server requires Go (with CGO/GCC) for the bridge component and Python/uv for the MCP server. The system-info server uses .NET. Mixing these in one repo adds build complexity without benefit.
- **Independent update cycles.** Third-party servers update on their own schedule (e.g., whatsmeow library updates when WhatsApp deprecates client versions). These updates should be pulled from upstream with a simple `git pull`, not managed through submodule pins or subtree merges.
- **Submodule/subtree complexity.** Git submodules are a common source of confusion (detached HEAD, forgotten `--recurse-submodules`, stale pins). Git subtree merges pollute the commit history. Neither approach adds enough value to justify the complexity for a personal project.

## Consequences

**Easier:**

- Updating a third-party server is a simple `git pull` in its own directory
- No build toolchain conflicts between servers with different languages
- Clear ownership boundary — upstream changes flow in cleanly
- The `mcp-servers` repo stays focused on first-party servers with a single build system

**Harder:**

- Users must clone and set up each third-party MCP server separately (documented in [WhatsApp MCP setup](../../design/tools/whatsapp-mcp/README.md) and [Getting Started](../../operations/getting-started.md))
- `config.json` contains absolute paths to each server, which are machine-specific
- No single command to set up all MCP servers at once
