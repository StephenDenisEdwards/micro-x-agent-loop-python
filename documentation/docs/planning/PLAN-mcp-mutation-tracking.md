# Plan: MCP Tool Mutation Tracking

## Status

Planned

## Problem

MCP (Model Context Protocol) tools execute through `McpToolProxy`, which does not implement `is_mutating` or `predict_touched_paths()`. This means MCP tools that write files are invisible to the checkpoint system — their mutations are never snapshotted and cannot be rewound.

Built-in tools (`write_file`, `append_file`, `bash`) all participate in checkpoint tracking. MCP tools are the only tool category that bypasses this safety net entirely.

## What This Plan Adds

An opt-in contract for MCP tools to declare mutation metadata, so:

1. **MCP file mutations get checkpointed** — before an MCP tool writes a file, the checkpoint system snapshots the original content, just like it does for `write_file`
2. **MCP mutations are rewindable** — `/rewind <checkpoint_id>` restores files changed by MCP tools
3. **Operators get consistent safety guarantees** — no gap between built-in and MCP tool coverage

## Current Architecture

### Tool Protocol (all tools must satisfy)

```python
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict
    is_mutating: bool
    predict_touched_paths(tool_input: dict) -> list[str]
    execute(tool_input: dict) -> str
```

### Built-in tool support

| Tool | `is_mutating` | `predict_touched_paths` |
|------|:---:|---|
| `write_file` | `True` | Returns `[path]` from input |
| `append_file` | `True` | Returns `[path]` from input |
| `bash` | `True` | Parses shell command for redirects, rm, mv, etc. |
| `read_file` | `False` | `[]` |
| Other built-ins | `False` | `[]` |

### McpToolProxy today

```python
class McpToolProxy:
    name: str          # "{server}__{tool}"
    description: str
    input_schema: dict
    execute(...)       # Delegates to MCP session.call_tool()
    # MISSING: is_mutating, predict_touched_paths
```

`McpToolProxy` does not implement `is_mutating` or `predict_touched_paths` at all. The `MemoryFacade.maybe_track_mutation()` method checks `getattr(tool, "is_mutating", False)` which returns `False`, so MCP tools are never tracked.

### Checkpoint tracking flow

```
Agent._run_inner()
  → TurnEngine.run()
    → for each tool_use_block:
        → Agent.on_ensure_checkpoint_for_turn()  # creates checkpoint once per turn
        → Agent.on_maybe_track_mutation()         # snapshots files BEFORE execution
            → MemoryFacade.maybe_track_mutation()
                → checks tool.is_mutating
                → calls tool.predict_touched_paths(tool_input)
                → CheckpointManager.track_paths(paths)
        → tool.execute()                          # actual mutation happens here
```

## Design

### Approach: Server-level configuration

MCP servers declare mutation metadata via `config.json`, not via the MCP protocol itself (which has no mutation concept). This keeps the contract local and under operator control.

```json
{
  "McpServers": {
    "file-editor": {
      "command": "npx",
      "args": ["-y", "@file-editor/mcp-server"],
      "mutations": {
        "edit_file": {
          "path_params": ["file_path"]
        },
        "delete_file": {
          "path_params": ["path"]
        }
      }
    }
  }
}
```

- **`mutations`** (optional dict): keyed by MCP tool name (the raw name from the server, not the prefixed proxy name)
- **`path_params`** (list of strings): parameter names in the tool's `input_schema` that contain file paths to track

If a tool appears in `mutations`, `McpToolProxy` reports `is_mutating=True` and extracts paths from the named parameters.

### Why not auto-detect?

- The MCP protocol has no `is_mutating` field — we'd have to guess based on tool names/descriptions, which is unreliable
- False positives (tracking non-mutating tools) waste checkpoint storage; false negatives (missing actual mutations) defeat the purpose
- Operator-declared config is explicit, auditable, and correct by construction

### Why not per-tool protocol extension?

- The MCP spec doesn't support custom metadata on tool definitions
- Even if it did, trusting server self-declaration creates a security assumption: a malicious MCP server could lie about mutation status
- Config-level declaration puts the operator in control

## Implementation

### 1. `mcp/mcp_tool_proxy.py` — Add mutation support

Add `mutations_config` parameter to constructor. Implement `is_mutating` and `predict_touched_paths`:

```python
class McpToolProxy:
    def __init__(self, ..., mutations_config: dict | None = None):
        self._mutations_config = mutations_config  # e.g. {"path_params": ["file_path"]}

    @property
    def is_mutating(self) -> bool:
        return self._mutations_config is not None

    def predict_touched_paths(self, tool_input: dict) -> list[str]:
        if self._mutations_config is None:
            return []
        paths = []
        for param in self._mutations_config.get("path_params", []):
            val = tool_input.get(param)
            if isinstance(val, str) and val.strip():
                paths.append(val)
        return paths
```

### 2. `mcp/mcp_manager.py` — Pass mutation config to proxies

When creating `McpToolProxy` instances, look up the tool name in the server's `mutations` config:

```python
mutations_map = server_config.get("mutations", {})
for tool_def in tool_list:
    mutations_config = mutations_map.get(tool_def.name)
    proxy = McpToolProxy(..., mutations_config=mutations_config)
```

### 3. `app_config.py` — No changes needed

`mcp_server_configs` already passes the full server config dict through, so `mutations` is available to `McpManager`.

### 4. Tests

- `McpToolProxy` with no mutations config: `is_mutating=False`, `predict_touched_paths=[]`
- `McpToolProxy` with mutations config: `is_mutating=True`, returns correct paths
- `McpToolProxy` with mutations config but missing params in input: returns empty
- Integration: MCP tool mutation flows through `MemoryFacade.maybe_track_mutation()` to checkpoint

## File Summary

| File | Action |
|------|--------|
| `src/micro_x_agent_loop/mcp/mcp_tool_proxy.py` | Add `mutations_config`, `is_mutating`, `predict_touched_paths` |
| `src/micro_x_agent_loop/mcp/mcp_manager.py` | Pass `mutations` config to proxy constructor |
| `tests/mcp/test_mcp_tool_proxy_mutations.py` | **New** — proxy mutation tests |
| `tests/memory/test_facade_mcp_mutations.py` | **New** — integration test with facade |

## Risk Register

1. **MCP tools with unpredictable paths** — Some tools generate output paths dynamically (e.g. based on content hashing). `path_params` won't cover these. Mitigation: best-effort, same as bash. Document that dynamic paths require the MCP server to return path info in its result, which could be tracked in a future phase.

2. **Operator misconfiguration** — Wrong `path_params` means wrong files get tracked or real mutations get missed. Mitigation: log warnings when configured path params are missing from tool input; document examples clearly.

3. **Checkpoint storage growth** — MCP tools that write large files will increase backup blob size. Mitigation: existing checkpoint storage bounds apply; no new risk beyond what `write_file` already creates.

4. **Breaking change to McpToolProxy** — Adding required protocol methods changes the class contract. Mitigation: both new methods have safe defaults (`False` and `[]`), and the MCP proxy is internal, not a public API.

5. **No MCP spec support** — This is a custom extension. If MCP adds native mutation metadata later, we'd want to migrate. Mitigation: the config-based approach is a thin layer; migrating to protocol-native metadata would only change the config source, not the proxy logic.

## Verification

1. `python -m pytest tests/mcp/ -v`
2. `python -m pytest tests/memory/ -v`
3. `python -m pytest tests/ -v` (full suite)
4. Manual: configure an MCP server with `mutations`, run a mutating tool, verify checkpoint is created, rewind restores the file
