# Plan: Migrate Codegen Template from Python to TypeScript

**Status: Planned**

## Problem

The Python codegen template (`tools/template/`) has systemic runtime issues on Windows:

1. **Dependency mismatch.** The codegen MCP server runs via `uv run` (its own Python environment). Generated tasks run as subprocesses needing `tenacity`, `mcp`, `anthropic`, `python-dotenv` — which live in the main project's `.venv`, not the codegen server's environment. Current workaround: hardcode `VENV_PYTHON` path to the project's `.venv/Scripts/python.exe`.

2. **Windows pipe inheritance hangs.** `subprocess.run(capture_output=True)` hangs when grandchild processes (MCP servers spawned by the task) inherit pipe handles. Current workaround: write stdout/stderr to temp files instead of pipes.

3. **`sys.unraisablehook` noise.** Asyncio subprocess transport cleanup on Windows fires tracebacks after MCP servers shut down. Current workaround: monkey-patch `sys.unraisablehook` to suppress.

4. **No isolated environment.** The template has no `pyproject.toml` or `package.json`. It's a loose collection of `.py` files that assume the right venv is active.

These are not bugs — they're consequences of Python's subprocess and async story on Windows. Each one has a workaround, but the workarounds are fragile and accumulate.

## Proposed Solution

Migrate the codegen template to TypeScript/Node. The generated task apps become Node projects instead of Python packages.

### Why TypeScript

- **Same ecosystem as MCP servers.** All existing MCP servers are TypeScript/Node. The template would use the same MCP SDK, same patterns, same tooling.
- **No venv issues.** `npm install` creates a local `node_modules/` — self-contained, no path gymnastics.
- **No pipe inheritance hangs.** Node's `child_process` doesn't suffer from the Windows handle inheritance problem.
- **LLM generates TypeScript well.** Claude produces reliable TypeScript for structured data processing tasks.
- **The MCP SDK is mature in TypeScript.** The Python MCP SDK has known edge cases (structuredContent not propagating, etc.).

### What Changes

| Component | Current (Python) | Proposed (TypeScript) |
|-----------|-----------------|----------------------|
| Template location | `tools/template/*.py` | `tools/template-ts/` |
| Template infrastructure | `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, `utils.py`, `test_base.py` | `src/index.ts`, `src/mcp-client.ts`, `src/tools.ts`, `src/utils.ts` |
| Dependency declaration | `requirements.txt` (added as fix) | `package.json` |
| Task execution | `python -m tools.<task_name>` | `npx tsx tools/<task_name>/src/index.ts` or `npm start` in task dir |
| Test framework | `unittest` | `vitest` or `node:test` |
| Generated code language | Python | TypeScript |

### Codegen Server Changes (`mcp_servers/python/codegen/main.py`)

- `build_system_prompt()` — rewrite for TypeScript: types, imports, async patterns, tools.ts signatures
- `parse_files()` — parse `=== filename.ts ===` blocks instead of `=== filename.py ===`
- `copy_template()` — copy from `tools/template-ts/`
- `_run_tests_sync()` — run `npm test` or `npx vitest run` instead of `python -m unittest`
- `run_task()` — run `npm start` or `npx tsx src/index.ts` instead of `python -m tools.<task_name>`
- `INFRASTRUCTURE_FILES` — update to TypeScript filenames
- `VENV_PYTHON` — no longer needed; use `npx` or `node`

### Template Infrastructure (`tools/template-ts/`)

**`package.json`** — declares dependencies:
- `@anthropic-ai/sdk`
- `@modelcontextprotocol/sdk`
- `dotenv`
- `tsx` (dev)
- `vitest` (dev)

**`src/index.ts`** — entry point (equivalent of `__main__.py`):
- Load `.env`, read config, connect MCP servers, call `runTask()`, shut down

**`src/mcp-client.ts`** — MCP client (equivalent of `mcp_client.py`):
- Connect to stdio MCP servers, call tools, return typed results
- No tenacity needed — simple retry loop with exponential backoff

**`src/tools.ts`** — typed wrappers (equivalent of `tools.py`):
- Same function signatures, returns typed objects
- Existing TypeScript MCP servers already return structured JSON

**`src/utils.ts`** — file utilities:
- `writeFile()`, `appendFile()` — async wrappers

**`src/test-base.ts`** — test utilities:
- Helper factories for test fixtures

### Migration Strategy

Generated task apps are disposable — they're regenerated from prompts each time. No need to migrate existing apps or maintain backward compatibility.

1. **Build the TypeScript template** in `tools/template-ts/`.
2. **Switch the codegen server** to use it. Delete the Python template.

### Task Execution Flow (After Migration)

```
generate_code("job_search", prompt)
  → copy tools/template-ts/ to tools/job_search/
  → LLM generates TypeScript files (task.ts, collector.ts, scorer.ts, etc.)
  → write files to tools/job_search/src/
  → run `npm install` in tools/job_search/
  → run `npm test` (vitest)
  → if tests fail, ask LLM to fix, re-run (up to 3 rounds)

run_task("job_search")
  → run `npm start` in tools/job_search/
  → stdout/stderr captured normally (no pipe hacks needed)
```

## Risks

- **LLM TypeScript generation quality.** Need to validate that the system prompt produces reliable TypeScript. The existing Python prompt has been iterated on extensively.
- **`npm install` speed.** First run in a new task dir takes a few seconds for `npm install`. Subsequent runs use cached `node_modules/`.
## Out of Scope

- Changing the codegen MCP server itself from Python to TypeScript (it's fine as Python — it just makes API calls and writes files)

## Dependencies

- Node.js and npm must be available on the system (already required for MCP servers)
- TypeScript MCP SDK (`@modelcontextprotocol/sdk`)
