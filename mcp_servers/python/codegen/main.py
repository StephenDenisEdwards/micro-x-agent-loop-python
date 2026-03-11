"""Codegen MCP Server — generates and runs TypeScript task apps.

Tools:
  generate_code(task_name, prompt, model?) — generate a task app via mini agentic loop
  run_task(task_name) — run a previously generated task app
"""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

load_dotenv()

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", ""))
WORKING_DIR = Path(os.environ.get("WORKING_DIR", ""))
TEMPLATE_DIR = PROJECT_ROOT / "tools" / "template-ts"
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16384
MAX_TURNS = 10
MAX_TEST_ROUNDS = 3
# Infrastructure files in src/ that the LLM must not read or modify
INFRASTRUCTURE_FILES = {"index.ts", "mcp-client.ts", "llm.ts", "tools.ts", "utils.ts", "test-base.ts"}
# Directories/files to exclude when copying the template
TEMPLATE_IGNORE = shutil.ignore_patterns("node_modules", "dist", "*.tsbuildinfo")

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


def copy_template(task_name: str) -> tuple[Path, str]:
    """Copy tools/template-ts/ to tools/<task_name>/ (excluding node_modules).

    If it already exists, append _2, _3, etc.
    Returns (target_dir, actual_task_name).
    """
    base = PROJECT_ROOT / "tools" / task_name
    target = base
    actual_name = task_name
    suffix = 1
    while target.exists():
        suffix += 1
        actual_name = f"{task_name}_{suffix}"
        target = PROJECT_ROOT / "tools" / actual_name
    shutil.copytree(TEMPLATE_DIR, target, ignore=TEMPLATE_IGNORE)
    # Verify key infrastructure files exist
    for f in INFRASTRUCTURE_FILES:
        if not (target / "src" / f).exists():
            raise FileNotFoundError(f"src/{f} missing after template copy")
    return target, actual_name


def _npm_install_sync(target_dir: Path) -> tuple[bool, str]:
    """Run npm install in the target directory. Returns (success, output)."""
    try:
        proc = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=str(target_dir),
            capture_output=True,
            stdin=subprocess.DEVNULL,
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
    if filename in INFRASTRUCTURE_FILES:
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


def build_system_prompt(task_name: str, tools_ts: str) -> str:
    """Build the system prompt for TypeScript code generation."""
    return f"""You are a TypeScript code generator. Output only code files, no prose.

## Non-negotiables
- Do not call any tool unless the user prompt explicitly references a file not already in this prompt.
- Infrastructure is sealed: index.ts, mcp-client.ts, llm.ts, tools.ts, utils.ts, test-base.ts. Do not inspect, read, or modify them.
- Do not output prose, explanations, or commentary — only the file manifest.

## Runtime contract
Target directory: tools/{task_name}/src/

task.ts MUST export:
- SERVERS: string[] — MCP server names (e.g. ["google", "linkedin"])
- async function runTask(clients: Clients, config: Record<string, unknown>): Promise<void>
  config is internal infrastructure (working directory, log paths, etc.) — do NOT
  read task-specific parameters from it. Everything the task needs is in the user
  prompt or discoverable via the available tools.

Available imports (from files in the same src/ directory):
- import {{ ... }} from "./tools.js"; (typed MCP wrappers — signatures below)
- import type {{ Clients }} from "./tools.js"; (type for the clients dict)
- import {{ writeFile, appendFile }} from "./utils.js"; (both async)
  - await writeFile(path, content, config) — overwrites, returns resolved path string
  - await appendFile(path, content, config) — appends, returns resolved path string
  - When writing in stages, writeFile first, appendFile after.
- import {{ createMessage, streamMessage, estimateCost, type Usage }} from "./llm.js"; (only if LLM calls needed)
- import {{ makeJobserveJob, makeLinkedinJob, makeEmail }} from "./test-base.js"; (test fixtures only)
- Optional modules: collector.ts, scorer.ts, processor.ts — import with ./module.js extension

IMPORTANT: All relative imports MUST use the .js extension (e.g. "./collector.js"), even for .ts files.
This is required by Node16 module resolution with ESM.

tools.ts signatures:
{tools_ts}

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
- Import test fixtures: import {{ makeJobserveJob, makeLinkedinJob, makeEmail }} from "./test-base.js";
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
        if filename in INFRASTRUCTURE_FILES:
            skipped.append(filename)
            continue
        if not filename.endswith(".ts"):
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

    If tests fail, continue the existing conversation to ask the LLM to fix.
    Mutates `files` in-place if source fixes are applied.
    """
    test_files = {k: v for k, v in files.items() if k.endswith(".test.ts")}
    if not test_files:
        await ctx.info("No test files generated — skipping validation")
        return {"skipped": True, "reason": "no test files"}

    await ctx.info(f"Running {len(test_files)} test file(s)...")

    total_input = 0
    total_output = 0
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

        async with client.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            system=cached_system,
            messages=messages,
            tools=cached_tools,
        ) as stream:
            response = await stream.get_final_message()

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        response_text = "".join(b.text for b in response.content if b.type == "text")
        messages.append({"role": "assistant", "content": [
            {"type": "text", "text": response_text}
        ]})

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

    # Step 2: Read tools.ts for system prompt
    tools_ts = (target_dir / "src" / "tools.ts").read_text(encoding="utf-8")

    # Step 3: Build system prompt and first user message
    system_prompt = build_system_prompt(task_name, tools_ts)
    first_message = build_user_message(prompt)
    messages = [{"role": "user", "content": first_message}]

    # Step 4: Agentic loop (uses streaming to avoid SDK timeout on long generations)
    await ctx.info("Phase 1: Generating code...")
    client = AsyncAnthropic()
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation_tokens = 0
    total_cache_read_tokens = 0
    resolved_model = model  # will be replaced by response.model (full ID with date suffix)
    turns = 0

    # Enable prompt caching: system prompt and tools are identical across
    # turns in the agentic loop, so mark them with cache_control breakpoints.
    cached_system = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
    ]
    cached_tools = [{**READ_FILE_TOOL, "cache_control": {"type": "ephemeral"}}]

    try:
        for turn in range(MAX_TURNS):
            turns += 1
            await ctx.info(f"  Turn {turns}...")
            async with client.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                system=cached_system,
                messages=messages,
                tools=cached_tools,
            ) as stream:
                response = await stream.get_final_message()

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            total_cache_creation_tokens += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0) or 0
            resolved_model = response.model

            # Append assistant response to conversation
            # Convert content blocks to serializable dicts
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                await ctx.info(f"  Code generation complete ({turns} turn(s))")
                break

            if response.stop_reason == "tool_use":
                tool_results, files_read = _process_tool_calls(response)
                for f in files_read:
                    await ctx.info(f"  Reading file: {f}")
                messages.append({"role": "user", "content": tool_results})
                continue

            if response.stop_reason == "max_tokens":
                await ctx.info(f"  Hit max_tokens on turn {turns} — continuing...")
                messages.append({"role": "user", "content":
                    "Your response was cut off. Continue exactly where you left off."
                })
                continue
        else:
            await ctx.error(f"Agentic loop exhausted after {MAX_TURNS} turns")
            return _error_result(
                f"Agentic loop exhausted after {MAX_TURNS} turns without completing.",
                task_name,
            )
    except Exception as e:
        await ctx.error(f"LLM call failed: {e}")
        return _error_result(f"LLM call failed: {e}", task_name)

    # Step 5: Extract text from ALL assistant messages (handles max_tokens continuations)
    response_text = ""
    for msg in messages:
        if msg["role"] == "assistant":
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    response_text += block["text"]

    # Step 6: Parse files from response
    files, skipped = parse_files(response_text)

    if not files:
        await ctx.error("No files parsed from LLM response")
        return _error_result(
            f"No files parsed from LLM response. First 500 chars: {response_text[:500]}",
            task_name,
        )
    if "task.ts" not in files:
        await ctx.error(f"task.ts missing from response. Got: {', '.join(files.keys())}")
        return _error_result(
            f"task.ts missing from response. Got: {', '.join(files.keys())}",
            task_name,
        )

    # Step 7: Write generated files to src/
    await ctx.info(f"Writing {len(files)} file(s): {', '.join(sorted(files))}")
    src_dir = target_dir / "src"
    for filename, content in files.items():
        filepath = src_dir / filename
        filepath.write_text(content, encoding="utf-8")

    # Step 8: Install dependencies
    await ctx.info("Installing dependencies (npm install)...")
    npm_ok, npm_output = await asyncio.to_thread(_npm_install_sync, target_dir)
    if not npm_ok:
        await ctx.error(f"npm install failed: {npm_output[-500:]}")
        return _error_result(f"npm install failed in tools/{task_name}/", task_name)
    await ctx.info("  Dependencies installed")

    # Step 9: Validate — run tests, fix failures
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
    except Exception as e:
        await ctx.error(f"Validation error: {e}")
        validation = {"error": str(e), "tests_passed": False}

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
        "turns": turns,
        "validation": validation,
    }

    summary_lines = [
        f"Generated {len(files)} files for tools/{task_name}/src/:",
        *[f"  - {f}" for f in sorted(files.keys())],
        f"Model: {model} | Tokens: {total_input_tokens} in, {total_output_tokens} out | Turns: {turns}",
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

    summary_lines.append(f"Run with: codegen__run_task(task_name=\"{task_name}\")")

    await ctx.info("Done.")
    return CallToolResult(
        content=[TextContent(type="text", text="\n".join(summary_lines))],
        structuredContent=structured,
        isError=False,
    )


@mcp.tool()
async def run_task(ctx: Context, task_name: str,
                   timeout_seconds: int = 600) -> CallToolResult:
    """Run a previously generated TypeScript task app.

    Args:
        task_name: Name of the task (e.g. "job_search"). Must exist under tools/<task_name>/.
        timeout_seconds: Maximum time to allow the task to run (default 600 = 10 minutes).
    """
    await ctx.info(f"run_task(task_name={task_name!r})")
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
    try:
        try:
            proc = subprocess.run(
                ["npx", "tsx", "src/index.ts"],
                cwd=str(task_dir),
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
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

    output = stdout
    if stderr:
        output += "\n--- stderr ---\n" + stderr

    structured = {
        "task_name": task_name,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }

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
