# ADR-027: Native tools in codegen tasks (in-process, not MCP subprocess)

## Status

Accepted — 2026-06-02. **Amends [ADR-019](./ADR-019-typescript-codegen-template.md)** (the codegen template now ships native-tool wrappers, not only MCP wrappers) and **builds on [ADR-025](./ADR-025-native-core-tools-mcp-for-subsystems.md)** (which moved core primitives in-process *for the agent* but left codegen tasks unable to reach them).

## Context

[ADR-025](./ADR-025-native-core-tools-mcp-for-subsystems.md) moved the core primitives — `filesystem` (read/write/append/delete/edit/grep/glob/bash/save_memory) and `system-info` — out of MCP servers and into **in-process Python `Tool` objects** in the agent. Crucially, `filesystem` is therefore **no longer present in `config.McpServers`**.

[ADR-019](./ADR-019-typescript-codegen-template.md) made codegen-generated tasks standalone **TypeScript/Node apps**. Each task declares the upstream servers it needs (`SERVERS`), and the template runtime (`tools/_runtime/`, `src/index.ts → connectUpstream`) **spawns its own subprocess** for each one from `config.McpServers`. The template's typed wrappers in `tools.ts` (`fsRead`, `fsBash`, `fsGrep`, …) call `get(clients, "filesystem").callTool("bash", …)` — i.e. they assume `filesystem` is an MCP server.

These two ADRs collided. A generated task declaring `SERVERS=["filesystem"]` and calling `fsBash` fails at runtime with `MCP server 'filesystem' not connected`: there is no `filesystem` entry in `config.McpServers` to spawn, because ADR-025 made it native. The capability the task wants exists only as an in-process Python object inside a *different* process (the agent) that the task cannot reach.

This is not a "standalone tasks can't use MCP" limitation — tasks *do* spawn their own MCP subprocesses for the servers that still are MCP (gmail, github, web, …). It is specifically that the native primitives have no MCP server to spawn anymore.

A codegen task is a separate OS process. To give it a native capability, that capability must be implemented *in the task's own process* — it cannot be shared from the agent's Python process.

## Decision

Codegen tasks reach the native primitives **in-process**, mirroring the agent's own native-tools architecture rather than reintroducing a subprocess.

- A new **`tools/_runtime/src/native/`** module provides in-process implementations of the native servers:
  - `filesystem.ts` — a faithful TypeScript port of the per-tool logic in `mcp_servers/ts/packages/filesystem` (the 9 tools + `PathPolicy`), minus the MCP server/logging shell.
  - `system-info.ts` — a Node port (`os` / `fs.statfs`) of `src/micro_x_agent_loop/native_tools/system_info.py`.
  - `client.ts` — `NativeClient`, an **in-process `IMcpClient`** that dispatches `callTool(name, args)` to those implementations and surfaces errors exactly as a failed MCP tool call would.
- `IMcpClient` is extracted in `mcp-client.ts` as the surface the wrappers depend on (`name` / `listTools` / `callTool` / `close`); both `McpClient` and `NativeClient` implement it, and the `Clients` map is `Record<string, IMcpClient>`.
- `connectUpstream` (template `index.ts`) treats `filesystem` and `system-info` as **native servers**: for those it injects a `NativeClient` (no subprocess); all other `SERVERS` entries spawn an MCP subprocess as before.
- The existing `fsRead`/`fsWrite`/`fsBash`/`fsGrep`/`fsGlob` wrappers are **unchanged** (now native-backed), and the parity wrappers `fsAppend`/`fsDelete`/`fsEdit`/`fsSaveMemory` + `systemInfo`/`diskInfo`/`networkInfo` are added.
- The native filesystem sandbox is driven by the agent's top-level **`Filesystem`** config block (`WorkingDir`/`AllowedDirs`/`ReadonlyDirs`/`MemoryDir`) — the same source ADR-025 moved the agent's roots to — read by `createNativeClient`.

Fully-qualified tool names (`filesystem__bash`, `system-info__system_info`, …) and the wrapper signatures are preserved, so generated task code is unchanged and tasks stay agnostic to whether a capability is native or MCP.

## Consequences

### Positive
- The ADR-019/ADR-025 collision is resolved: tasks declaring `filesystem`/`system-info` work, with no subprocess and the same `PathPolicy` sandbox the agent enforces.
- No transport tax inside tasks for the hot primitives (consistent with ADR-025's rationale, now applied to tasks too).
- `system-info` becomes available to tasks for the first time (it never had a TS MCP server to spawn).
- Tasks remain hosting-agnostic: native vs MCP is an `connectUpstream` detail, invisible to `task.ts`.

### Negative
- **A third source of truth for filesystem semantics.** The same 9 tools now exist as (1) the TS MCP server `mcp_servers/ts/packages/filesystem`, (2) the Python native tools `src/micro_x_agent_loop/native_tools/filesystem`, and (3) this codegen-runtime TS port. These can drift. This is the [ISSUE-007](../../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) drift risk ADR-025 already flagged for copy #2, now extended to copy #3. Mitigation: the port files carry "keep in sync" headers; the long-term fix is to characterize the contract with shared tests (PLAN-behavioural-eval-suite) rather than trust three hand-maintained copies.
- New dependencies in `tools/_runtime`: `@vscode/ripgrep` (a ~10 MB binary), `fast-glob`, `mammoth`. Installed once in the shared `_runtime`, not per task.
- A bug in the runtime port runs in the task process. Acceptable: tasks are short-lived and already untrusted-by-isolation; a task crash doesn't touch the agent.
- **Windows path-guard parity caveat:** the bash path-guard is a verbatim port, so on Windows it flags only `C:\…`, `\\UNC`, and `..` traversal — a POSIX-style `/etc/passwd` is not treated as a path candidate (it is meaningless on Windows). This matches the source filesystem server; it is not a port regression, but it is weaker than a POSIX host's guard.

### Neutral / on the record
- Already-generated tasks are **not** updated retroactively; they copied the old template at generation time. They must be regenerated, or have `src/index.ts` + `src/tools.ts` re-synced from `codegen-templates/template-ts/src/` (done for `extract_train_receipts`).
- `codegen` itself stays an MCP subprocess (ADR-025's isolatable-subsystem rule is unchanged).

## Alternatives considered

- **Spawn the existing filesystem TS MCP server for tasks (Route B).** Add a `filesystem` entry back to the config codegen tasks load, pointing at `mcp_servers/ts/packages/filesystem`; the existing wrappers then work with zero template-code change. **Rejected:** it reintroduces the per-task subprocess + stdio transport tax that ADR-025 deliberately removed, partially reopening what ADR-025 closed; it does nothing for `system-info` (no TS server exists); and it leaves the task's hot path slower for no benefit.
- **Cross-import the MCP filesystem package's `register*` functions into the runtime via an in-memory MCP loopback.** Would avoid copy #3. **Rejected:** couples the codegen runtime to the separate `mcp_servers/ts` workspace build and to `@micro-x-ai/mcp-shared` runtime values; fragile across the separate-repo boundary (ADR-006) for little gain over a contained port.
- **Leave it broken; tell tasks to use Node builtins directly.** What the regenerated `extract_train_receipts_2` did ad hoc (`fs`, `child_process`). **Rejected as the general answer:** it drops the `PathPolicy` sandbox, duplicates ad-hoc IO in every task, and gives no `grep`/`glob`/`system-info` parity.
