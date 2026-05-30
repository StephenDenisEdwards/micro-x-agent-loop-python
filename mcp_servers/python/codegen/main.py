"""Codegen MCP Server — generates and runs TypeScript task apps.

Tools:
  generate_code(task_name, prompt, model?) — generate a task app via mini agentic loop
  list_tasks() — list previously generated task apps with their input schemas
  run_task(task_name, params?) — run a previously generated task app with parameters
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

# On Windows, npm/npx are .cmd files that require shell=True to be found
# by subprocess.run(). On Unix, shell=False is preferred for safety.
_SHELL = sys.platform == "win32"

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

load_dotenv()

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", ""))
WORKING_DIR = Path(os.environ.get("WORKING_DIR", ""))
TEMPLATE_DIR = PROJECT_ROOT / "codegen-templates" / "template-ts"
RUNTIME_DIR = PROJECT_ROOT / "tools" / "_runtime"
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16384
MAX_TURNS = 10
MAX_TEST_ROUNDS = 3
# Per-task sealed files (live in tools/<task>/src/, must exist after template copy)
PER_TASK_SEALED_FILES = {
    "index.ts",
    "config.ts",
    "tool-loader.ts",
    "tools.ts",
    "tool-types.ts",
}
# Runtime files (live in tools/_runtime/src/, never copied into a task)
RUNTIME_FILES = {"llm.ts", "mcp-client.ts", "utils.ts", "test-base.ts", "tool-def.ts"}
# All filenames the LLM must not generate or read — defense-in-depth for parse_files / read_file
BLOCKED_FILES = PER_TASK_SEALED_FILES | RUNTIME_FILES
# Directories/files to exclude when copying the template
TEMPLATE_IGNORE = shutil.ignore_patterns("node_modules", "dist", "*.tsbuildinfo", "scripts")

READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read a user-referenced file (criteria, specs, data). Only for files "
        "explicitly mentioned in the user prompt that are NOT already provided "
        "in the system prompt. Will reject infrastructure/scaffold files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the working directory.",
            }
        },
        "required": ["path"],
    },
}

mcp = FastMCP("codegen")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http_mcp_url_envvars() -> dict[str, str]:
    """Compute MICRO_X_<NAME>_MCP_URL env-var pairs for HTTP/SSE-transport
    MCP servers in the agent's resolved config.

    Reads `MICRO_X_AGENT_CONFIG_JSON` (forwarded by the agent's McpManager).
    For each server with `transport: "sse"` or `transport: "http"`, derives
    a URL from explicit `url` or composed from `host` + `port` (or
    `--port <N>` in args). Returns empty dict if the env var is not set
    (running the task standalone — falls back to stdio spawn).

    Mirrors the convention used in tools/_runtime/src/mcp-client.ts so the
    spawned task subprocess's McpClient picks up the same name. See
    PLAN-shared-mcp-http-transport.md Phases 2 and 3.
    """
    raw = os.environ.get("MICRO_X_AGENT_CONFIG_JSON")
    if not raw:
        return {}
    try:
        config = json.loads(raw)
    except Exception:
        return {}

    mcp_servers = config.get("McpServers") or {}
    out: dict[str, str] = {}
    for name, server_config in mcp_servers.items():
        if not isinstance(server_config, dict):
            continue
        transport = server_config.get("transport", "stdio")
        if transport not in ("sse", "http"):
            continue
        try:
            url = _build_mcp_url(server_config, transport)
        except Exception:
            continue
        envvar = f"MICRO_X_{name.upper().replace('-', '_')}_MCP_URL"
        out[envvar] = url
    return out


def _build_mcp_url(server_config: dict, transport: str) -> str:
    """Build the URL for an HTTP/SSE-transport server. Explicit `url` wins;
    otherwise compose from `host` + `port` (or `--port <N>` in args)."""
    if "url" in server_config:
        return str(server_config["url"])
    host = server_config.get("host") or "localhost"
    port = server_config.get("port")
    if port is None:
        args = server_config.get("args") or []
        for i, a in enumerate(args):
            if a == "--port" and i + 1 < len(args):
                port = args[i + 1]
                break
    if port is None:
        raise ValueError("HTTP/SSE server has no port (set 'port' or include '--port <N>' in args)")
    path = "/sse" if transport == "sse" else ""
    return f"http://{host}:{port}{path}"


def _error_result(message: str, task_name: str = "") -> CallToolResult:
    """Return a CallToolResult with isError=True."""
    structured = {"error": message}
    if task_name:
        structured["task_name"] = task_name
    return CallToolResult(
        content=[TextContent(type="text", text=f"ERROR: {message}")],
        structuredContent=structured,
        isError=True,
    )


def copy_template(task_name: str, max_attempts: int = 20) -> tuple[Path, str]:
    """Copy codegen-templates/template-ts/ to tools/<task_name>/ (excluding node_modules).

    If it already exists, append _2, _3, etc. Uses copytree's own
    FileExistsError to avoid TOCTOU races with concurrent calls.
    Returns (target_dir, actual_task_name).
    """
    actual_name = task_name
    suffix = 1
    for _ in range(max_attempts):
        target = PROJECT_ROOT / "tools" / actual_name
        try:
            shutil.copytree(TEMPLATE_DIR, target, ignore=TEMPLATE_IGNORE)
        except FileExistsError:
            suffix += 1
            actual_name = f"{task_name}_{suffix}"
            continue
        # Verify per-task sealed files exist (runtime files live in tools/_runtime/, not in the task)
        for f in PER_TASK_SEALED_FILES:
            if not (target / "src" / f).exists():
                raise FileNotFoundError(f"src/{f} missing after template copy")
        return target, actual_name
    raise RuntimeError(f"Could not create task directory after {max_attempts} attempts")


def _npm_install_sync(target_dir: Path) -> tuple[bool, str]:
    """Run npm install in the target directory. Returns (success, output)."""
    try:
        proc = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=str(target_dir),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            shell=_SHELL,
            timeout=120,
        )
        output = proc.stdout.decode("utf-8", errors="replace")
        if proc.stderr:
            output += "\n" + proc.stderr.decode("utf-8", errors="replace")
        return proc.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "npm install timed out after 120 seconds."
    except Exception as e:
        return False, f"npm install failed: {e}"


def _execute_read_file(path: str) -> str:
    """Read a file from WORKING_DIR with path traversal protection."""
    filename = Path(path).name
    if filename in BLOCKED_FILES:
        return (
            f"ACCESS_DENIED: '{filename}' is a sealed infrastructure file "
            "and cannot be read. All information you need is in the system prompt."
        )

    try:
        resolved_working = WORKING_DIR.resolve()
        target = (WORKING_DIR / path).resolve()
        # Verify the resolved path is within WORKING_DIR
        target.relative_to(resolved_working)
    except (ValueError, OSError):
        return f"Error: path '{path}' is outside the working directory."

    if not target.exists():
        return f"Error: file '{path}' not found."
    if not target.is_file():
        return f"Error: '{path}' is not a file."

    try:
        return target.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading '{path}': {e}"


def _process_tool_calls(response) -> tuple[list[dict], list[str]]:
    """Process tool_use blocks from the response, execute read_file.

    Returns (tool_result_messages, list_of_files_read).
    """
    results = []
    files_read = []
    for block in response.content:
        if block.type == "tool_use":
            if block.name == "read_file":
                file_path = block.input.get("path", "")
                files_read.append(file_path)
                content = _execute_read_file(file_path)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })
            else:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: unknown tool '{block.name}'.",
                    "is_error": True,
                })
    return results, files_read


def _serialize_content(response) -> list[dict]:
    """Convert response content blocks to serializable dicts."""
    content = []
    for block in response.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return content


def _extract_text(messages: list[dict], start: int = 0) -> str:
    """Extract text from assistant messages in messages[start:]."""
    text = ""
    for msg in messages[start:]:
        if msg["role"] == "assistant":
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block["text"]
    return text


def _describe_task_sync(task_dir: Path) -> tuple[bool, dict | str]:
    """Run `npx tsx src/index.ts --describe` in the task and parse the JSON it
    prints to stdout. Returns (ok, payload-or-error-string).

    The describe handler is provided by codegen-templates/template-ts/ and prints a JSON object
    with keys tool_name, description, input_schema (JSON Schema). Requires
    node_modules to be installed.
    """
    try:
        proc = subprocess.run(
            ["npx", "tsx", "src/index.ts", "--describe"],
            cwd=str(task_dir),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            shell=_SHELL,
            timeout=60,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")
            return False, f"--describe exited {proc.returncode}: {stderr[-500:]}"
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        if not stdout:
            return False, "--describe produced no output"
        return True, json.loads(stdout)
    except subprocess.TimeoutExpired:
        return False, "--describe timed out after 60 seconds"
    except Exception as e:
        return False, f"--describe failed: {e}"


def _update_manifest(task_name: str, target_dir: Path, files: dict[str, str]) -> None:
    """Add or update an entry in tools/manifest.json for the generated task.

    The entry includes the tool's JSON Schema captured via `--describe` so the
    agent can introspect parameters without spawning the task as an MCP server.
    """
    manifest_path = PROJECT_ROOT / "tools" / "manifest.json"

    # Read existing manifest or create new one
    manifest: dict[str, dict] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Extract tool metadata from the generated task.ts
    task_ts = files.get("task.ts", "")
    tool_name = task_name
    description = f"Generated task: {task_name}"

    # Parse TOOL_NAME and TOOL_DESCRIPTION from the source
    name_match = re.search(r'export\s+const\s+TOOL_NAME\s*=\s*["\']([^"\']+)["\']', task_ts)
    if name_match:
        tool_name = name_match.group(1)
    desc_match = re.search(r'export\s+const\s+TOOL_DESCRIPTION\s*=\s*["\']([^"\']+)["\']', task_ts)
    if desc_match:
        description = desc_match.group(1)

    # Capture the JSON Schema(s) from the generated app. zodToJsonSchema can
    # fail if the LLM emitted a non-standard Zod type — record the failure but
    # still write the manifest entry so the task is discoverable.
    #
    # The --describe payload is the multi-tool shape {server_name, tools: [...]}
    # with singular tool_name/description/input_schema fields populated for
    # single-tool apps as a back-compat shim. Mirror that shape in the manifest:
    # always write the tools[] array; keep singular fields populated when
    # there's only one tool so older readers continue to work.
    input_schema: dict | None = None
    tools_list: list[dict] | None = None
    describe_error: str | None = None
    describe_ok, payload = _describe_task_sync(target_dir)
    if describe_ok and isinstance(payload, dict):
        raw_tools = payload.get("tools")
        if isinstance(raw_tools, list):
            tools_list = [t for t in raw_tools if isinstance(t, dict)]
        schema = payload.get("input_schema")
        if isinstance(schema, dict):
            input_schema = schema
        # Prefer values from the live module over regex parsing
        if isinstance(payload.get("tool_name"), str):
            tool_name = payload["tool_name"]
        if isinstance(payload.get("description"), str):
            description = payload["description"]
    else:
        describe_error = payload if isinstance(payload, str) else "unknown describe error"

    entry: dict = {
        "tool_name": tool_name,
        "description": description,
        "created": date.today().isoformat(),
        "input_schema": input_schema,
        "tools": tools_list,
        "server": {
            "transport": "stdio",
            "command": "npx",
            "args": ["tsx", "src/index.ts", "--config", "../../config.json"],
            "cwd": f"tools/{task_name}/",
        },
    }
    if describe_error:
        entry["describe_error"] = describe_error

    manifest[task_name] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


async def _llm_loop(
    client: AsyncAnthropic,
    model: str,
    messages: list[dict],
    cached_system: list[dict],
    cached_tools: list[dict],
    ctx: Context,
    max_turns: int,
) -> tuple[str, int, int, int, int, str]:
    """Run LLM turns until end_turn, handling tool_use and max_tokens.

    Appends assistant/user messages to `messages` in-place.
    Returns (text, input_tokens, output_tokens, cache_creation_tokens,
             cache_read_tokens, resolved_model).
    Only returns text from assistant messages added during this call.
    """
    start_len = len(messages)
    total_in = 0
    total_out = 0
    total_cache_creation = 0
    total_cache_read = 0
    resolved_model = model

    for turn in range(max_turns):
        await ctx.info(f"  Turn {turn + 1}...")
        async with client.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            system=cached_system,
            messages=messages,
            tools=cached_tools,
        ) as stream:
            response = await stream.get_final_message()

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        total_cache_creation += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        resolved_model = response.model

        messages.append({"role": "assistant", "content": _serialize_content(response)})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results, files_read = _process_tool_calls(response)
            for f in files_read:
                await ctx.info(f"  Reading file: {f}")
            messages.append({"role": "user", "content": tool_results})
            continue

        if response.stop_reason == "max_tokens":
            await ctx.info(f"  Hit max_tokens on turn {turn + 1} — continuing...")
            messages.append({"role": "user", "content":
                "Your response was cut off. Continue exactly where you left off."
            })
            continue
    else:
        raise RuntimeError(f"Agentic loop exhausted after {max_turns} turns without completing.")

    text = _extract_text(messages, start_len)
    return text, total_in, total_out, total_cache_creation, total_cache_read, resolved_model


def build_system_prompt(task_name: str, tools_ts: str, test_base_ts: str) -> str:
    """Build the system prompt for TypeScript code generation."""
    return f"""You are a TypeScript code generator. Output only code files, no prose.

## Non-negotiables
- Do not call any tool unless the user prompt explicitly references a file not already in this prompt.
- Per-task sealed files (in tools/{task_name}/src/): index.ts, config.ts, tool-loader.ts, tools.ts, tool-types.ts. Do not inspect or modify.
- Shared runtime files (in tools/_runtime/src/): llm.ts, utils.ts, mcp-client.ts, test-base.ts, tool-def.ts. Do not inspect, modify, or generate. Imported via "../../_runtime/src/<name>.js" relative paths.
- Do not output prose, explanations, or commentary — only the file manifest.

## Runtime contract
Target directory: tools/{task_name}/src/

The generated app is an MCP server. By default it exposes a single tool — use
the single-tool shape unless the requirements clearly describe multiple related
tools that should share state (e.g. a processor that exposes both "process" and
"draft_reply"). Do not pick the multi-tool shape just to add optionality.

### Single-tool shape (default)

task.ts MUST export:

- SERVERS: string[] — upstream MCP server names to connect (e.g. ["google", "linkedin"])
- TOOL_NAME: string — snake_case tool name (e.g. "{task_name}")
- TOOL_DESCRIPTION: string — one-line description for tool discovery
- TOOL_INPUT_SCHEMA: Zod raw shape — the tool's input parameters (see format below)
- async function handleTool(input, clients, profile, config): Promise<Record<string, unknown>>

handleTool receives:
- input: the parsed tool parameters (typed by TOOL_INPUT_SCHEMA)
- clients: Clients — connected upstream MCP servers
- profile: Record<string, unknown> — contents of profile.json (user-specific config)
- config: Record<string, unknown> — infrastructure config (working directory, etc.)

handleTool MUST return a plain object (Record<string, unknown>) with the result data.
Do NOT write to stdout or use console.log for results — return the data.

### Multi-tool shape (only when the requirements describe multiple related tools)

Replace TOOL_NAME / TOOL_DESCRIPTION / TOOL_INPUT_SCHEMA / handleTool with:

- SERVERS: string[] — same as above (union of upstream servers needed across all tools)
- SERVER_NAME: string — optional; the MCP server's name (defaults to "{task_name}")
- TOOLS: ToolDef[] — array of {{name, description, inputSchema, handler}} entries

```
import {{ defineTools }} from "../../_runtime/src/tool-def.js";
export const SERVERS: string[] = ["google"];
export const TOOLS = defineTools([
  {{
    name: "process_alerts",
    description: "Process pending job alerts.",
    inputSchema: {{ dryRun: z.boolean().default(false).describe("...") }},
    handler: async (input, clients, profile, config) => {{ ... }},
  }},
  {{
    name: "draft_reply",
    description: "Draft a reply to a specific job.",
    inputSchema: {{ jobId: z.string().describe("...") }},
    handler: async (input, clients, profile, config) => {{ ... }},
  }},
]);
```

Each handler has the same signature as single-tool handleTool. Tool names
within one app MUST be unique. Avoid generic names ("fetch", "parse") that
might collide with upstream MCP tools.
Use console.error for debug logging only.

## TOOL_INPUT_SCHEMA format
Use a flat Zod raw shape (NOT z.object()). Example:
```
export const TOOL_INPUT_SCHEMA = {{
  days: z.number().default(1).describe("How far back to search"),
  outputDir: z.string().default(".").describe("Where to write the report"),
}};
```
Each key is a parameter name, each value is a Zod type with .describe().
Use .default() for parameters with sensible defaults.
Use .optional() for truly optional parameters without defaults.

## profile.json
If the requirements specify user-specific configuration (skills, preferences,
scoring criteria, exclusion rules, etc.), generate a profile.json file with
those values. The file is read at startup and passed to handleTool as `profile`.

Generate profile.json using the === profile.json === delimiter, same as .ts files.
If no profile data is needed, do not generate profile.json (an empty default exists).

Available imports:
- import {{ z }} from "zod"; (for TOOL_INPUT_SCHEMA)
- import {{ ... }} from "./tools.js"; (typed MCP wrappers — signatures below; per-task file in src/)
- import type {{ Clients }} from "./tools.js"; (type for the clients dict)
- import type {{ ... }} from "./tool-types.js"; (auto-generated strict input/output types per MCP tool — per-task file in src/)
- import {{ writeFile, appendFile }} from "../../_runtime/src/utils.js"; (both async — shared runtime)
  - await writeFile(path, content, config) — overwrites, returns resolved path string
  - await appendFile(path, content, config) — appends, returns resolved path string
  - For cumulative/log-style files that grow across runs, always use appendFile only.
  - For single-shot reports written in stages within ONE run, writeFile first, appendFile after.
- import {{ createMessage, streamMessage, estimateCost, type Usage }} from "../../_runtime/src/llm.js"; (shared runtime; only if LLM calls needed)
  - createMessage(spec, maxTokens, messages, options?) → Promise<[text: string, usage: Usage]>
  - streamMessage(spec, maxTokens, messages, options?) → Promise<[text: string, usage: Usage]>
  - `spec` selects the provider + model. Use "provider/model" to choose a provider explicitly,
    or a bare model id (which defaults to Anthropic). Supported:
    - anthropic/claude-haiku-4-5-20251001 (cheap, fast — preferred for scoring/classification)
    - anthropic/claude-sonnet-4-6 (balanced — for harder reasoning or longer outputs)
    - anthropic/claude-opus-4-7 (most capable — only when explicitly required)
    - openai/gpt-4.1-mini, openai/gpt-4o-mini, gemini/gemini-2.5-flash, deepseek/deepseek-chat
    - ollama/<model> (local, no API key; e.g. ollama/llama3.2:3b)
    A bare "claude-sonnet-4-6" is equivalent to "anthropic/claude-sonnet-4-6".
    Do NOT use claude-3-*, claude-3-5-*, or any 2024-dated Claude id — they are retired.
  - Prefer reading the model from the task's profile when one is provided (e.g. profile.rank_model),
    so the user controls provider + model without code changes.
  - The API key is read from .env by provider (ANTHROPIC_API_KEY / OPENAI_API_KEY /
    GEMINI_API_KEY / DEEPSEEK_API_KEY; Ollama needs none).
  - messages is {{ role: "user" | "assistant"; content: string }}[] (e.g. [{{ role: "user", content: prompt }}]); options is {{ system?, temperature? }}
  - Both return a tuple; destructure the text: const [text, usage] = await createMessage(...)
  - Do NOT access .content on the return value — it is a string, not a Message object.
- import {{ makeJobserveJob, makeLinkedinJob, makeEmail }} from "../../_runtime/src/test-base.js"; (test fixtures only — shared runtime)
- Optional modules you create yourself in the task src/: collector.ts, scorer.ts, processor.ts — import with ./module.js extension

IMPORTANT: All relative imports MUST use the .js extension (e.g. "./collector.js"), even for .ts files.
This is required by Node16 module resolution with ESM.

tools.ts signatures (and tool-types.ts — the strict types they reference):
{tools_ts}

test-base.ts fixtures (use these exact field names and value formats in tests):
{test_base_ts}

## Gmail data format
gmailSearch query for JobServe: use "from:jobserve" (not a full email address — the sender varies).
gmailRead returns {{messageId, from, to, date, subject, body}}.
The body field is html-to-text converted email HTML:
- Links appear as: text [url]  (e.g. "APPLY NOW [https://example.com/apply]")
- Content is POSITIONAL — visual blocks separated by blank lines — NOT labeled key-value pairs.
- Do NOT parse email bodies by looking for "FieldName: value" patterns. These rarely exist in HTML emails.
- Parse by position: split on blank lines to get ordered blocks (title, location, rate, duration, etc.).
- Footer/boilerplate typically appears after "Apply [url]" or similar markers.
- JobServe email links expire. Extract the jid parameter from the URL and construct a stable link:
  https://www.jobserve.com/gb/en/JobLanding.aspx?jid=<jid>

## Rules
- All scoring, ranking, filtering, statistics, and report formatting MUST be pure TypeScript. No LLM calls for these.
- Only create .ts files.
- Use new Date() for today's date.
- Use Intl.DateTimeFormat for locale-aware date formatting.
- Prefer const over let. Use strict TypeScript types where possible.
- Use async/await (not .then() chains).

## Generation budget
- Total generated code: under 800 lines across all files.
- Unit tests: max 10 tests per module. Test core logic only.
- No JSDoc on internal functions. No comments that restate the code.

## Unit tests
For every module with pure-logic functions, produce a <module>.test.ts file:
- Use vitest: import {{ describe, it, expect }} from "vitest";
- Import test fixtures: import {{ makeJobserveJob, makeLinkedinJob, makeEmail }} from "../../_runtime/src/test-base.js";
- Import source modules with .js extension:
  import {{ parseJobserveEmail, extractRateStr }} from "./collector.js";
- Do NOT test async functions, MCP calls, or anything requiring network/IO.
- Do NOT mock modules or use vi.mock() — test pure functions only.

## Tool rules
You must not call read_file unless the user prompt explicitly mentions a filename you have not seen.

## Output format
Return each file using this exact delimiter format:

=== task.ts ===
<code>

=== collector.ts ===
<code>

=== collector.test.ts ===
<code>

No markdown fences. No explanatory text between files. Only code."""


def build_user_message(user_prompt: str) -> str:
    """Build the first user message with requirements."""
    return f"Requirements:\n\n{user_prompt}"


def parse_files(response_text: str) -> tuple[dict[str, str], list[str]]:
    """Parse === filename === delimited blocks from the response. Returns (files_dict, skipped_list)."""
    files: dict[str, str] = {}
    skipped: list[str] = []
    pattern = r"===\s*(\S+)\s*===\s*\n(.*?)(?====\s*\S+\s*===|\Z)"
    for match in re.finditer(pattern, response_text, re.DOTALL):
        filename = match.group(1).strip("\"'`")
        content = match.group(2).strip("\n")
        # Strip markdown fences if the LLM wraps code despite instructions
        content = re.sub(r"^```(?:typescript|ts)?\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
        if filename in BLOCKED_FILES:
            skipped.append(filename)
            continue
        if not (filename.endswith(".ts") or filename.endswith(".json")):
            skipped.append(filename)
            continue
        # Reject filenames with path separators — all generated files must be
        # flat in the src/ directory. The LLM sometimes generates paths like
        # "src/task.ts" during fix rounds, which would crash the writer.
        if "/" in filename or "\\" in filename:
            skipped.append(filename)
            continue
        files[filename] = content
    return files, skipped


# ---------------------------------------------------------------------------
# Validation — run vitest, fix failures
# ---------------------------------------------------------------------------


def _run_tests_sync(target_dir: Path) -> tuple[bool, str]:
    """Run vitest in the target directory. Returns (passed, output).

    Synchronous — call via asyncio.to_thread() to avoid blocking the event loop.
    """
    try:
        proc = subprocess.run(
            ["npx", "vitest", "run", "--reporter=verbose"],
            cwd=str(target_dir),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            shell=_SHELL,
            timeout=60,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        output = stdout
        if stderr:
            output += "\n" + stderr
        return proc.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Tests timed out after 60 seconds."
    except Exception as e:
        return False, f"Failed to run tests: {e}"


async def _validate_code(ctx: Context, client: AsyncAnthropic, model: str,
                         task_name: str, target_dir: Path,
                         files: dict[str, str],
                         messages: list[dict],
                         cached_system: list[dict],
                         cached_tools: list[dict]) -> dict:
    """Run the test files that were generated alongside the source code.

    If tests fail, continue the existing conversation to ask the LLM to fix
    using the same _llm_loop helper (supports tool_use and max_tokens).
    Mutates `files` in-place if source fixes are applied.
    """
    test_files = {k: v for k, v in files.items() if k.endswith(".test.ts")}
    if not test_files:
        await ctx.info("No test files generated — skipping validation")
        return {"skipped": True, "reason": "no test files"}

    await ctx.info(f"Running {len(test_files)} test file(s)...")

    total_input = 0
    total_output = 0
    total_cache_creation = 0
    total_cache_read = 0
    rounds = 0
    all_passed = False
    last_output = ""

    for round_num in range(1, MAX_TEST_ROUNDS + 1):
        rounds = round_num
        passed, output = await asyncio.to_thread(_run_tests_sync, target_dir)
        last_output = output

        if passed:
            await ctx.info("  All tests passed!")
            all_passed = True
            break

        fail_count = output.count("FAIL") + output.count("AssertionError") + output.count("Error:")
        await ctx.info(f"  {fail_count} failure(s) — asking LLM to fix (round {round_num}/{MAX_TEST_ROUNDS})...")

        # Continue the codegen conversation with test failure output
        messages.append({"role": "user", "content":
            f"The unit tests failed. Here is the output:\n\n```\n{output}\n```\n\n"
            "Fix the source code and/or tests. Return ALL files that need changes "
            "using the same === filename === format."
        })

        response_text, in_tok, out_tok, cache_create, cache_read, _ = await _llm_loop(
            client, model, messages, cached_system, cached_tools, ctx, max_turns=3
        )
        total_input += in_tok
        total_output += out_tok
        total_cache_creation += cache_create
        total_cache_read += cache_read

        parsed, _ = parse_files(response_text)
        for filename, content in parsed.items():
            files[filename] = content
            (target_dir / "src" / filename).write_text(content, encoding="utf-8")
            await ctx.info(f"  Updated: {filename}")

    if not all_passed:
        await ctx.warning(f"  Validation incomplete after {MAX_TEST_ROUNDS} rounds")

    return {
        "test_rounds": rounds,
        "tests_passed": all_passed,
        "test_files_generated": sorted(test_files.keys()),
        "test_output": last_output[-2000:] if last_output else "",
        "validation_input_tokens": total_input,
        "validation_output_tokens": total_output,
        "validation_cache_creation_tokens": total_cache_creation,
        "validation_cache_read_tokens": total_cache_read,
    }


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def generate_code(ctx: Context, task_name: str, prompt: str,
                        model: str = DEFAULT_MODEL) -> CallToolResult:
    """Generate a TypeScript task app from the template using a mini agentic loop with read_file.

    Args:
        task_name: Name for the task (e.g. "job_search"). Creates tools/<task_name>/.
        prompt: The full task requirements as text. If the prompt references files
            (e.g. criteria files, schemas), the codegen LLM will read them automatically.
        model: Claude model to use. Defaults to claude-sonnet-4-6.
    """
    await ctx.info(f"generate_code(task_name={task_name!r}, model={model})")

    # Validate environment
    if not PROJECT_ROOT or not PROJECT_ROOT.exists():
        await ctx.error(f"PROJECT_ROOT not set or missing: {PROJECT_ROOT}")
        return _error_result(f"PROJECT_ROOT not set or missing: {PROJECT_ROOT}", task_name)
    if not TEMPLATE_DIR.exists():
        await ctx.error(f"Template directory missing: {TEMPLATE_DIR}")
        return _error_result(f"Template directory missing: {TEMPLATE_DIR}", task_name)

    # Step 1: Copy template (excludes node_modules)
    await ctx.info("Copying template...")
    try:
        target_dir, task_name = copy_template(task_name)
    except Exception as e:
        await ctx.error(f"Template copy failed: {e}")
        return _error_result(f"Template copy failed: {e}", task_name)
    await ctx.info(f"Target: tools/{task_name}/")

    # All steps after template copy are wrapped so we can clean up on failure.
    # Cleanup removes the copied directory to avoid orphaned templates.
    def _cleanup() -> None:
        shutil.rmtree(target_dir, ignore_errors=True)

    # Step 2: Read tools.ts (+ generated tool-types.ts) and test-base.ts for system prompt.
    # tool-types.ts holds the strict input/output types derived from the upstream MCP
    # schemas (regenerated via `npm run regen-tool-types`). Feeding it alongside
    # tools.ts lets the LLM see the real allowed values (enums etc.) for tool args
    # — without it, the wrappers reference type aliases the LLM can't resolve.
    tools_ts = (target_dir / "src" / "tools.ts").read_text(encoding="utf-8")
    tool_types_path = target_dir / "src" / "tool-types.ts"
    tool_types_ts = tool_types_path.read_text(encoding="utf-8") if tool_types_path.exists() else ""
    test_base_ts = (RUNTIME_DIR / "src" / "test-base.ts").read_text(encoding="utf-8")

    # Step 3: Build system prompt and first user message
    combined_tools_ts = (
        f"// === src/tool-types.ts (generated from MCP schemas) ===\n{tool_types_ts}\n\n"
        f"// === src/tools.ts (hand-written wrappers) ===\n{tools_ts}"
        if tool_types_ts
        else tools_ts
    )
    system_prompt = build_system_prompt(task_name, combined_tools_ts, test_base_ts)
    first_message = build_user_message(prompt)
    messages = [{"role": "user", "content": first_message}]

    # Step 4: Agentic loop (uses streaming to avoid SDK timeout on long generations)
    await ctx.info("Phase 1: Generating code...")
    client = AsyncAnthropic()

    # Enable prompt caching: system prompt and tools are identical across
    # turns in the agentic loop, so mark them with cache_control breakpoints.
    cached_system = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
    ]
    cached_tools = [{**READ_FILE_TOOL, "cache_control": {"type": "ephemeral"}}]

    try:
        response_text, total_input_tokens, total_output_tokens, \
            total_cache_creation_tokens, total_cache_read_tokens, \
            resolved_model = await _llm_loop(
                client, model, messages, cached_system, cached_tools, ctx, MAX_TURNS
            )
    except RuntimeError as e:
        await ctx.error(str(e))
        _cleanup()
        return _error_result(str(e), task_name)
    except Exception as e:
        await ctx.error(f"LLM call failed: {e}")
        _cleanup()
        return _error_result(f"LLM call failed: {e}", task_name)

    await ctx.info("  Code generation complete")

    # Step 5: Parse files from response
    files, skipped = parse_files(response_text)

    if not files:
        await ctx.error("No files parsed from LLM response")
        _cleanup()
        return _error_result(
            f"No files parsed from LLM response. First 500 chars: {response_text[:500]}",
            task_name,
        )
    if "task.ts" not in files:
        await ctx.error(f"task.ts missing from response. Got: {', '.join(files.keys())}")
        _cleanup()
        return _error_result(
            f"task.ts missing from response. Got: {', '.join(files.keys())}",
            task_name,
        )

    # Step 6: Write generated files to src/ (and profile.json to task root)
    await ctx.info(f"Writing {len(files)} file(s): {', '.join(sorted(files))}")
    src_dir = target_dir / "src"
    for filename, content in files.items():
        if filename == "profile.json":
            (target_dir / "profile.json").write_text(content, encoding="utf-8")
        else:
            filepath = src_dir / filename
            filepath.write_text(content, encoding="utf-8")

    # Step 7: Install dependencies
    await ctx.info("Installing dependencies (npm install)...")
    npm_ok, npm_output = await asyncio.to_thread(_npm_install_sync, target_dir)
    if not npm_ok:
        await ctx.error(f"npm install failed: {npm_output[-500:]}")
        _cleanup()
        return _error_result(f"npm install failed in tools/{task_name}/", task_name)
    await ctx.info("  Dependencies installed")

    # Step 8: Validate — run tests, fix failures
    await ctx.info("Phase 2: Validation...")
    validation = {}
    try:
        validation = await _validate_code(
            ctx, client, model, task_name, target_dir, files,
            messages, cached_system, cached_tools
        )
        # Update total usage with validation costs
        total_input_tokens += validation.get("validation_input_tokens", 0)
        total_output_tokens += validation.get("validation_output_tokens", 0)
        total_cache_creation_tokens += validation.get("validation_cache_creation_tokens", 0)
        total_cache_read_tokens += validation.get("validation_cache_read_tokens", 0)
    except Exception as e:
        await ctx.error(f"Validation error: {e}")
        validation = {"error": str(e), "tests_passed": False}

    # Step 9: Update tools/manifest.json
    try:
        _update_manifest(task_name, target_dir, files)
        await ctx.info(f"Manifest updated: tools/manifest.json")
    except Exception as e:
        await ctx.warning(f"Manifest update failed (non-fatal): {e}")

    # Build result
    structured = {
        "task_name": task_name,
        "target_dir": str(target_dir),
        "files_written": sorted(files.keys()),
        "files_skipped": skipped,
        "provider": "anthropic",
        "model": resolved_model,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_creation_input_tokens": total_cache_creation_tokens,
        "cache_read_input_tokens": total_cache_read_tokens,
        "validation": validation,
    }

    summary_lines = [
        f"Generated {len(files)} files for tools/{task_name}/src/:",
        *[f"  - {f}" for f in sorted(files.keys())],
        f"Model: {model} | Tokens: {total_input_tokens} in, {total_output_tokens} out",
    ]
    if skipped:
        summary_lines.append(f"Skipped: {', '.join(skipped)}")

    # Validation summary
    if validation.get("skipped"):
        summary_lines.append(f"Validation: skipped ({validation.get('reason', 'n/a')})")
    elif validation.get("tests_passed"):
        summary_lines.append(
            f"Validation: PASSED ({validation.get('test_rounds', 0)} round(s), "
            f"{len(validation.get('test_files_generated', []))} test file(s))"
        )
    elif validation.get("error"):
        summary_lines.append(f"Validation: ERROR — {validation['error']}")
    else:
        summary_lines.append(
            f"Validation: FAILED after {validation.get('test_rounds', 0)} round(s)"
        )

    summary_lines.append(
        f"Run it with: codegen__run_task(task_name=\"{task_name}\", params={{...}})"
    )
    summary_lines.append(
        "Use codegen__list_tasks() to see the input schema for this and other generated tasks."
    )

    await ctx.info("Done.")
    return CallToolResult(
        content=[TextContent(type="text", text="\n".join(summary_lines))],
        structuredContent=structured,
        isError=False,
    )


@mcp.tool()
async def list_tasks(ctx: Context) -> CallToolResult:
    """List previously generated task apps with their descriptions and input schemas.

    Reads tools/manifest.json. For entries that do not yet have an input_schema
    (e.g. tasks generated before this field existed), runs `--describe` on the
    task and writes the schema back to the manifest opportunistically.
    """
    await ctx.info("list_tasks()")
    manifest_path = PROJECT_ROOT / "tools" / "manifest.json"
    if not manifest_path.exists():
        return CallToolResult(
            content=[TextContent(type="text", text="No tasks generated yet.")],
            structuredContent={"tasks": []},
            isError=False,
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        return _error_result(f"Failed to read manifest: {e}")

    tasks: list[dict] = []
    manifest_dirty = False
    for task_name, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        task_dir = PROJECT_ROOT / "tools" / task_name
        if not task_dir.exists():
            continue  # Skip stale entries pointing at deleted directories

        # Backfill input_schema for legacy entries — only if node_modules exists.
        if entry.get("input_schema") is None and (task_dir / "node_modules").exists():
            ok, payload = await asyncio.to_thread(_describe_task_sync, task_dir)
            if ok and isinstance(payload, dict):
                schema = payload.get("input_schema")
                if isinstance(schema, dict):
                    entry["input_schema"] = schema
                    manifest_dirty = True

        tasks.append({
            "task_name": task_name,
            "tool_name": entry.get("tool_name", task_name),
            "description": entry.get("description", ""),
            "input_schema": entry.get("input_schema"),
            "tools": entry.get("tools"),
            "created": entry.get("created"),
        })

    if manifest_dirty:
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        except Exception as e:
            await ctx.warning(f"Could not write backfilled schemas to manifest: {e}")

    def _render_schema(schema: dict | None, indent: str) -> list[str]:
        """Render an input_schema's parameter list, one line per parameter."""
        out: list[str] = []
        props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
        required = set((schema.get("required") or []) if isinstance(schema, dict) else [])
        for pname, pschema in props.items():
            if not isinstance(pschema, dict):
                continue
            ptype = pschema.get("type", "?")
            req = "required" if pname in required else "optional"
            desc = pschema.get("description", "")
            default = f", default={pschema['default']!r}" if "default" in pschema else ""
            out.append(f"{indent}- {pname}: {ptype} ({req}{default}) {desc}".rstrip())
        return out

    # Build a compact text summary. Multi-tool tasks list each exposed tool
    # underneath the task name; single-tool tasks render as before.
    lines = [f"{len(tasks)} task(s):"]
    for t in tasks:
        tools = t.get("tools")
        if isinstance(tools, list) and len(tools) > 1:
            lines.append(f"  {t['task_name']} — {t['description']} ({len(tools)} tools)")
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                lines.append(
                    f"    {tool.get('tool_name', '?')} — {tool.get('description', '')}"
                )
                lines.extend(_render_schema(tool.get("input_schema"), "      "))
        else:
            lines.append(f"  {t['task_name']} — {t['description']}")
            lines.extend(_render_schema(t.get("input_schema"), "    "))
            if t.get("input_schema") is None and not isinstance(tools, list):
                lines.append("    (input schema not yet captured — call codegen__run_task to trigger)")

    return CallToolResult(
        content=[TextContent(type="text", text="\n".join(lines))],
        structuredContent={"tasks": tasks},
        isError=False,
    )


@mcp.tool()
async def run_task(ctx: Context, task_name: str,
                   params: dict | None = None,
                   tool: str | None = None,
                   timeout_seconds: int = 600) -> CallToolResult:
    """Run a previously generated TypeScript task app with parameters.

    Args:
        task_name: Name of the task (e.g. "job_search"). Must exist under tools/<task_name>/.
        params: Dict of input parameters matching the task's input_schema (see
            codegen__list_tasks). Defaults to {} — the task will use defaults
            for any parameter with a default, and Zod will reject the call if
            any required parameter is missing.
        tool: Name of the specific tool to run within the task. Only needed
            for multi-tool apps (where codegen__list_tasks shows >1 tool
            under the task). Single-tool apps default to their only tool.
        timeout_seconds: Maximum time to allow the task to run (default 600 = 10 minutes).
    """
    if params is None:
        params = {}
    await ctx.info(f"run_task(task_name={task_name!r}, tool={tool!r}, params={params!r})")
    task_dir = PROJECT_ROOT / "tools" / task_name
    if not task_dir.exists():
        await ctx.error(f"Task directory not found: tools/{task_name}/")
        return _error_result(f"Task directory not found: tools/{task_name}/", task_name)
    if not (task_dir / "src" / "task.ts").exists():
        await ctx.error(f"src/task.ts not found in tools/{task_name}/")
        return _error_result(f"src/task.ts not found in tools/{task_name}/", task_name)

    # Ensure dependencies are installed
    if not (task_dir / "node_modules").exists():
        await ctx.info("Installing dependencies (npm install)...")
        npm_ok, npm_output = await asyncio.to_thread(_npm_install_sync, task_dir)
        if not npm_ok:
            await ctx.error(f"npm install failed: {npm_output[-500:]}")
            return _error_result(f"npm install failed in tools/{task_name}/", task_name)

    await ctx.info(f"Running npx tsx src/index.ts in tools/{task_name}/ ...")
    timed_out = False
    _MAX_OUTPUT = 10_000  # Cap stdout/stderr in structured result

    # Build env for the subprocess, including MICRO_X_<NAME>_MCP_URL for any
    # MCP server in the agent's config that uses HTTP/SSE transport. The
    # task subprocess's McpClient will see these and connect to the agent's
    # already-running server instead of spawning its own (resolves
    # ISSUE-006 profile-lock contention for shared-state MCP servers like
    # @playwright/mcp). See PLAN-shared-mcp-http-transport.md Phase 3.
    subprocess_env = os.environ.copy()
    try:
        for env_name, env_url in _http_mcp_url_envvars().items():
            subprocess_env[env_name] = env_url
    except Exception as e:
        await ctx.warning(f"Could not derive MCP URL env vars (ignoring): {e}")

    try:
        config_path = str(PROJECT_ROOT / "config.json")
        cmd = ["npx", "tsx", "src/index.ts", "--run", "--config", config_path]
        if tool:
            cmd.extend(["--tool", tool])
        if params:
            cmd.extend(["--params", json.dumps(params)])
        proc = subprocess.run(
            cmd,
            cwd=str(task_dir),
            capture_output=True,
            shell=_SHELL,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            env=subprocess_env,
        )
        exit_code = proc.returncode
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = -1
        stdout = ""
        stderr = ""
    except Exception as e:
        await ctx.error(f"Failed to run task: {e}")
        return _error_result(f"Failed to run task: {e}", task_name)

    # Extract __USAGE__ sentinel emitted by _runtime/src/llm.ts on subprocess exit.
    # Strip it from the visible stderr so the user doesn't see the raw line.
    usage: dict | None = None
    cleaned_stderr_lines: list[str] = []
    for line in stderr.splitlines():
        if line.startswith("__USAGE__:"):
            try:
                usage = json.loads(line[len("__USAGE__:"):])
            except Exception:
                pass
            continue
        cleaned_stderr_lines.append(line)
    stderr = "\n".join(cleaned_stderr_lines)

    structured: dict = {
        "task_name": task_name,
        "exit_code": exit_code,
        "stdout": stdout[-_MAX_OUTPUT:],
        "stderr": stderr[-_MAX_OUTPUT:],
        "timed_out": timed_out,
    }

    # Build the visible text content. If the runtime emitted a __USAGE__
    # sentinel, prepend it as a prominent banner so the agent's summary
    # mentions it (LLMs tend to drop trailing detail when summarising).
    output_parts: list[str] = []
    if usage is not None:
        structured["_usage"] = usage
        cost = usage.get("cost_usd", 0.0)
        calls = usage.get("calls", 0)
        model = usage.get("model", "?")
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        output_parts.append(
            "=== TOOL LLM USAGE (NOT counted in /cost) ===\n"
            f"  model:    {model}\n"
            f"  calls:    {calls}\n"
            f"  tokens:   {in_tok:,} in / {out_tok:,} out\n"
            f"  cost_usd: ${cost:.4f}\n"
            "=============================================\n"
            "Please surface this cost block to the user verbatim in your reply.\n"
        )
    output_parts.append(stdout)
    if stderr:
        output_parts.append("--- stderr ---\n" + stderr)
    output = "\n".join(output_parts)

    if timed_out:
        msg = f"Task timed out after {timeout_seconds} seconds."
        if output.strip():
            msg += f"\n\nPartial output:\n{output}"
        await ctx.warning(f"Task timed out after {timeout_seconds}s")
        return CallToolResult(
            content=[TextContent(type="text", text=msg)],
            structuredContent=structured,
            isError=True,
        )

    if exit_code != 0:
        await ctx.error(f"Task failed (exit code {exit_code})")
        return CallToolResult(
            content=[TextContent(type="text", text=f"Task failed (exit code {exit_code}):\n{output}")],
            structuredContent=structured,
            isError=True,
        )

    await ctx.info("Task completed successfully")
    return CallToolResult(
        content=[TextContent(type="text", text=output)],
        structuredContent=structured,
        isError=False,
    )


if __name__ == "__main__":
    mcp.run()
