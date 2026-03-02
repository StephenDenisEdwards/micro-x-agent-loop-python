"""Codegen MCP Server — generates task app code via a single LLM call.

Exposes one tool: generate_code(task_name, prompt_file, model?)
The agent calls it, the server handles everything:
  copy template → read context → call Sonnet (no tools) → parse response → write files
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
MAX_TOKENS = 16384
INFRASTRUCTURE_FILES = {"__main__.py", "mcp_client.py", "llm.py", "tools.py", "utils.py"}

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


def build_prompt(task_name: str, tools_py: str, user_prompt: str) -> str:
    """Build the generation prompt — identical logic to tools/generate.py."""
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

Do NOT include `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, or `utils.py` in your output.

## User requirements

{user_prompt}"""


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
def generate_code(task_name: str, prompt_file: str, model: str = DEFAULT_MODEL) -> CallToolResult:
    """Generate a task app from the template using a single LLM call.

    Args:
        task_name: Name for the task (e.g. "job_search"). Creates tools/<task_name>/.
        prompt_file: Path to the user prompt file, relative to WORKING_DIR.
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

    # Step 2: Read context files
    tools_py = (target_dir / "tools.py").read_text(encoding="utf-8")
    user_prompt = prompt_path.read_text(encoding="utf-8")

    # Step 3: Build prompt and call LLM (no tools, single shot)
    prompt = build_prompt(task_name, tools_py, user_prompt)

    try:
        client = Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        return _error_result(f"LLM call failed: {e}", task_name)

    response_text = response.content[0].text
    usage = response.usage

    # Step 4: Parse files from response
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

    # Step 5: Write files
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
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }

    summary_lines = [
        f"Generated {len(files)} files for tools/{task_name}/:",
        *[f"  - {f}" for f in sorted(files.keys())],
        f"Model: {model} | Tokens: {usage.input_tokens} in, {usage.output_tokens} out",
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
