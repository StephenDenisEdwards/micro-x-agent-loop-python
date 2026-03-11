# ADR-019: TypeScript Codegen Template

## Status

Proposed

## Context

The codegen MCP server (`mcp_servers/python/codegen/main.py`) generates task apps by copying a Python template (`tools/template/`) and asking the LLM to fill in task-specific code. On Windows, this architecture has accumulated three distinct runtime problems:

1. **Dependency mismatch.** The codegen server runs in its own `uv` environment. Generated tasks run as subprocesses that need `tenacity`, `mcp`, `anthropic`, and `python-dotenv` — packages that live in the main project's `.venv`, not the codegen server's environment. Workaround: hardcode `VENV_PYTHON` to `.venv/Scripts/python.exe`.

2. **Windows pipe inheritance hangs.** `subprocess.run(capture_output=True)` hangs when grandchild processes (MCP servers spawned by the task) inherit pipe handles. After the task exits, `communicate()` blocks on stdout waiting for those orphan processes to close the handles. Workaround: write stdout/stderr to temp files instead of pipes.

3. **`sys.unraisablehook` noise.** Asyncio subprocess transport cleanup on Windows fires tracebacks after MCP servers shut down. Workaround: monkey-patch `sys.unraisablehook` to suppress them.

Each workaround is fragile in isolation; together they form an accumulating maintenance burden. These are not fixable bugs — they are consequences of Python's subprocess and async model on Windows.

A secondary problem: the template has no `pyproject.toml` or `package.json`. It is a loose collection of `.py` files that assume the correct venv is active, with no self-contained dependency declaration.

## Decision

Migrate the codegen template from Python to TypeScript. Generated task apps become Node.js projects instead of Python packages.

### Template structure (`tools/template-ts/`)

| File | Purpose |
|------|---------|
| `package.json` | Declares `@anthropic-ai/sdk`, `@modelcontextprotocol/sdk`, `dotenv`, `tsx` (dev), `vitest` (dev) |
| `src/index.ts` | Entry point — load `.env`, connect MCP servers, call `runTask()`, shut down |
| `src/mcp-client.ts` | MCP client — connect to stdio servers, call tools, return typed results |
| `src/tools.ts` | Typed wrappers around MCP tools (mirrors `tools.py`) |
| `src/utils.ts` | `writeFile()`, `appendFile()` async helpers |
| `src/test-base.ts` | Test fixture factories |

### Codegen server changes (`mcp_servers/python/codegen/main.py`)

- `build_system_prompt()` — rewritten for TypeScript: types, imports, async patterns, `tools.ts` signatures
- `parse_files()` — parses `=== filename.ts ===` blocks; rejects non-`.ts` files
- `copy_template()` — copies from `tools/template-ts/`
- `_run_tests_sync()` — runs `npx vitest run` instead of `python -m unittest`
- `run_task()` — runs `npm start` instead of `python -m tools.<task_name>`
- `INFRASTRUCTURE_FILES` — updated to TypeScript filenames
- `VENV_PYTHON` — removed; use `npx` or `node`

### Migration strategy

Generated task apps are disposable — they are regenerated from prompts each time. There is no need to migrate existing apps or maintain backward compatibility. The Python template (`tools/template/`) is deleted once the TypeScript template is validated.

## Consequences

### Positive

- **No venv issues.** `npm install` creates a local `node_modules/` — self-contained, no path gymnastics.
- **No pipe inheritance hangs.** Node's `child_process` does not suffer from the Windows handle inheritance problem.
- **No `unraisablehook` noise.** Node.js subprocess cleanup does not trigger asyncio teardown tracebacks.
- **Consistent ecosystem.** All MCP servers are already TypeScript/Node. The template uses the same SDK and patterns.
- **Self-contained dependency declaration.** `package.json` replaces the fragile venv assumption.

### Negative

- **`npm install` on first run.** Each new task directory requires an `npm install` before execution. Subsequent runs reuse `node_modules/`.
- **LLM TypeScript generation quality.** The system prompt for Python generation has been iterated on extensively. The TypeScript prompt must be validated to produce equivalent reliability.
- **Node.js required.** Node and npm must be available on the system. Already a requirement for the existing MCP servers.

### Neutral

- The codegen MCP server itself remains Python — it only makes API calls and writes files.
- Task app logic migrates from Python classes to TypeScript async functions with the same structure.
