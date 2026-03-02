"""Codegen MCP Server — generates task app code via a mini agentic loop.

Exposes one tool: generate_code(task_name, prompt_file, model?)
The agent calls it, the server handles everything:
  copy template → read context → agentic loop with read_file tool → parse response → write files
"""

import json
import os
import re
import shutil
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

load_dotenv()

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", ""))
WORKING_DIR = Path(os.environ.get("WORKING_DIR", ""))
TEMPLATE_DIR = PROJECT_ROOT / "tools" / "template"
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 32768
MAX_TURNS = 10
INFRASTRUCTURE_FILES = {"__main__.py", "mcp_client.py", "llm.py", "tools.py", "utils.py"}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read the contents of a file from the working directory. "
        "Use this to read files referenced in the user's prompt (e.g. criteria files, "
        "data files, schemas). Path is relative to the working directory."
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


def copy_template(task_name: str) -> Path:
    """Copy tools/template/ to tools/<task_name>/ using shutil (cross-platform)."""
    target = PROJECT_ROOT / "tools" / task_name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(TEMPLATE_DIR, target)
    # Verify key files exist
    for f in INFRASTRUCTURE_FILES:
        if not (target / f).exists():
            raise FileNotFoundError(f"{f} missing after template copy")
    return target


def _execute_read_file(path: str) -> str:
    """Read a file from WORKING_DIR with path traversal protection."""
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


def _process_tool_calls(response) -> list[dict]:
    """Process tool_use blocks from the response, execute read_file, return tool_result messages."""
    results = []
    for block in response.content:
        if block.type == "tool_use":
            if block.name == "read_file":
                file_path = block.input.get("path", "")
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
    return results


def _read_context_files(filenames: list[str]) -> str:
    """Read context files from WORKING_DIR and format them for the prompt."""
    if not filenames:
        return ""
    sections = []
    for name in filenames:
        path = WORKING_DIR / name if WORKING_DIR else Path(name)
        if not path.exists():
            sections.append(f"### {name}\n\n*(file not found)*")
            continue
        content = path.read_text(encoding="utf-8")
        sections.append(f"### {name}\n\n```\n{content}\n```")
    return "\n\n## Pre-loaded context files\n\n" + "\n\n".join(sections)


def build_system_prompt(task_name: str, tools_py: str) -> str:
    """Build the system prompt with role, template context, and output format rules."""
    return f"""You are a Python code generator. You will produce Python source files for a console app.

## Context

A template has been copied to `tools/{task_name}/`. It contains these infrastructure files that MUST NOT be modified:
- `__main__.py` — entry point, imports `SERVERS` and `run_task` from `task.py`
- `mcp_client.py` — MCP stdio client
- `llm.py` — LLM helper
- `tools.py` — typed MCP wrappers (shown below)
- `utils.py` — contains `write_file(path, content, config)` for UTF-8 file output

## tools.py (available MCP functions)

```python
{tools_py}
```

## Your task

Write the Python files needed to implement the user's requirements. You MUST produce `task.py`. You MAY also produce `collector.py`, `scorer.py`, and/or `processor.py` if the task is complex enough to warrant splitting.

### task.py requirements
- Export `SERVERS` — a list of MCP server name strings (e.g. `["google", "linkedin"]`)
- Export `async def run_task(clients: dict, config: dict) -> None`
- Use `from .tools import ...` for MCP calls
- Use `from .utils import write_file` for file output, always pass `config`
- Use relative imports only (`from .collector import ...`)

### Rules
- All scoring, ranking, filtering, statistics, and report formatting MUST be pure Python. No LLM calls for these.
- Only create `.py` files. No README, no docs, no markdown.
- Use `datetime.now()` for today's date.
- If the user prompt references other files (e.g. criteria files, data files), use the `read_file` tool to read them BEFORE generating code. Do not guess file contents.

## Output format

Return each file in this exact format (one block per file):

### FILE: task.py
```python
<code>
```

### FILE: collector.py
```python
<code>
```

(and so on for each file you create)

Do NOT include `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, or `utils.py` in your output."""


def build_user_message(user_prompt: str, context_files_text: str = "") -> str:
    """Build the first user message with requirements and any pre-loaded context files."""
    parts = ["## User requirements\n", user_prompt]
    if context_files_text:
        parts.append(context_files_text)
    parts.append(
        "\n\nIf the requirements reference any files you haven't seen yet, "
        "use the read_file tool to read them before generating code. "
        "Once you have all the context you need, generate the code."
    )
    return "\n".join(parts)


def parse_files(response_text: str) -> tuple[dict[str, str], list[str]]:
    """Parse FILE: blocks from the response. Returns (files_dict, skipped_list)."""
    files: dict[str, str] = {}
    skipped: list[str] = []
    pattern = r"### FILE:\s*(\S+)\s*\n```python\n(.*?)```"
    for match in re.finditer(pattern, response_text, re.DOTALL):
        filename = match.group(1)
        content = match.group(2)
        if filename in INFRASTRUCTURE_FILES:
            skipped.append(filename)
            continue
        if not filename.endswith(".py"):
            skipped.append(filename)
            continue
        files[filename] = content
    return files, skipped


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------


@mcp.tool()
def generate_code(task_name: str, prompt_file: str, context_files: list[str] | None = None,
                  model: str = DEFAULT_MODEL) -> CallToolResult:
    """Generate a task app from the template using a mini agentic loop with read_file.

    Args:
        task_name: Name for the task (e.g. "job_search"). Creates tools/<task_name>/.
        prompt_file: Path to the user prompt file, relative to WORKING_DIR.
        context_files: Optional list of additional files (relative to WORKING_DIR) to include
            in the generation prompt as context. Use this for data files referenced by the prompt
            (e.g. criteria files, schemas, examples). Pre-loading saves a round-trip.
        model: Claude model to use. Defaults to claude-sonnet-4-6.
    """
    # Validate environment
    if not PROJECT_ROOT or not PROJECT_ROOT.exists():
        return _error_result(f"PROJECT_ROOT not set or missing: {PROJECT_ROOT}", task_name)
    if not TEMPLATE_DIR.exists():
        return _error_result(f"Template directory missing: {TEMPLATE_DIR}", task_name)

    # Resolve prompt file
    prompt_path = WORKING_DIR / prompt_file if WORKING_DIR else Path(prompt_file)
    if not prompt_path.exists():
        return _error_result(f"Prompt file not found: {prompt_path}", task_name)

    # Step 1: Copy template
    try:
        target_dir = copy_template(task_name)
    except Exception as e:
        return _error_result(f"Template copy failed: {e}", task_name)

    # Step 2: Read tools.py and user prompt
    tools_py = (target_dir / "tools.py").read_text(encoding="utf-8")
    user_prompt = prompt_path.read_text(encoding="utf-8")

    # Step 3: Pre-load any explicit context_files (saves a round-trip)
    context_files_text = _read_context_files(context_files or [])

    # Step 4: Build system prompt and first user message
    system_prompt = build_system_prompt(task_name, tools_py)
    first_message = build_user_message(user_prompt, context_files_text)
    messages = [{"role": "user", "content": first_message}]

    # Step 5: Agentic loop (uses streaming to avoid SDK timeout on long generations)
    client = Anthropic()
    total_input_tokens = 0
    total_output_tokens = 0
    turns = 0

    try:
        for turn in range(MAX_TURNS):
            turns += 1
            with client.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=messages,
                tools=[READ_FILE_TOOL],
            ) as stream:
                response = stream.get_final_message()

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

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
                break

            if response.stop_reason == "tool_use":
                tool_results = _process_tool_calls(response)
                messages.append({"role": "user", "content": tool_results})
                continue

            if response.stop_reason == "max_tokens":
                return _error_result(
                    f"LLM hit max_tokens ({MAX_TOKENS}) on turn {turns}. "
                    "Response may be truncated.",
                    task_name,
                )
        else:
            return _error_result(
                f"Agentic loop exhausted after {MAX_TURNS} turns without completing.",
                task_name,
            )
    except Exception as e:
        return _error_result(f"LLM call failed: {e}", task_name)

    # Step 6: Extract text from final response
    response_text = ""
    for block in response.content:
        if block.type == "text":
            response_text += block.text

    # Step 7: Parse files from response
    files, skipped = parse_files(response_text)

    if not files:
        return _error_result(
            f"No files parsed from LLM response. First 500 chars: {response_text[:500]}",
            task_name,
        )
    if "task.py" not in files:
        return _error_result(
            f"task.py missing from response. Got: {', '.join(files.keys())}",
            task_name,
        )

    # Step 8: Write files
    for filename, content in files.items():
        filepath = target_dir / filename
        filepath.write_text(content, encoding="utf-8")

    # Build result
    structured = {
        "task_name": task_name,
        "target_dir": str(target_dir),
        "files_written": sorted(files.keys()),
        "files_skipped": skipped,
        "model": model,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "turns": turns,
    }

    summary_lines = [
        f"Generated {len(files)} files for tools/{task_name}/:",
        *[f"  - {f}" for f in sorted(files.keys())],
        f"Model: {model} | Tokens: {total_input_tokens} in, {total_output_tokens} out | Turns: {turns}",
    ]
    if skipped:
        summary_lines.append(f"Skipped: {', '.join(skipped)}")
    summary_lines.append(f"Run with: python -m tools.{task_name}")

    return CallToolResult(
        content=[TextContent(type="text", text="\n".join(summary_lines))],
        structuredContent=structured,
        isError=False,
    )


if __name__ == "__main__":
    mcp.run()
