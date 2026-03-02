"""Generate a task app from the template using a single LLM call.

Usage:
    python -m tools.generate <task_name>

Example:
    python -m tools.generate job_search

Copies tools/template/ to tools/<task_name>/, reads the ADAPT-PROMPT and
user prompt, sends one API call to Claude, and writes the generated files.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "tools" / "template"
ADAPT_PROMPT = PROJECT_ROOT / "tools" / "ADAPT-PROMPT.md"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16384


def copy_template(task_name: str) -> Path:
    """Copy template to tools/<task_name>/ using xcopy."""
    target = PROJECT_ROOT / "tools" / task_name
    if target.exists():
        print(f"Removing existing {target}...")
        subprocess.run(
            ["rmdir", "/s", "/q", str(target)],
            shell=True, check=True,
        )
    print(f"Copying template to tools/{task_name}/...")
    result = subprocess.run(
        ["xcopy", str(TEMPLATE_DIR), str(target), "/E", "/I", "/Y"],
        shell=True, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"xcopy failed:\n{result.stderr}")
        sys.exit(1)
    # Verify key files exist
    for f in ["__main__.py", "mcp_client.py", "tools.py", "utils.py", "task.py"]:
        if not (target / f).exists():
            print(f"ERROR: {f} missing after copy")
            sys.exit(1)
    print(f"Template copied. {sum(1 for _ in target.glob('*.py'))} Python files.")
    return target


def read_file(path: Path) -> str:
    """Read a UTF-8 file."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_user_prompt_path(adapt_text: str) -> Path | None:
    """Extract the user prompt file path from the ADAPT-PROMPT."""
    # Look for the file path in the last section
    match = re.search(r"```\s*\n(.+\.txt)\s*\n```", adapt_text)
    if match:
        return Path(match.group(1))
    return None


def build_prompt(task_name: str, tools_py: str, user_prompt: str) -> str:
    """Build the generation prompt."""
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


def parse_files(response_text: str) -> dict[str, str]:
    """Parse FILE: blocks from the response."""
    files = {}
    pattern = r"### FILE:\s*(\S+)\s*\n```python\n(.*?)```"
    for match in re.finditer(pattern, response_text, re.DOTALL):
        filename = match.group(1)
        content = match.group(2)
        # Skip infrastructure files even if the model returns them
        if filename in ("__main__.py", "mcp_client.py", "llm.py", "tools.py", "utils.py"):
            print(f"  Skipping {filename} (infrastructure)")
            continue
        if not filename.endswith(".py"):
            print(f"  Skipping {filename} (not a .py file)")
            continue
        files[filename] = content
    return files


def main() -> None:
    load_dotenv()

    if len(sys.argv) < 2:
        print("Usage: python -m tools.generate <task_name>")
        print("Example: python -m tools.generate job_search")
        sys.exit(1)

    task_name = sys.argv[1]

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Step 1: Copy template
    target_dir = copy_template(task_name)

    # Step 2: Read context files
    tools_py = read_file(target_dir / "tools.py")
    adapt_text = read_file(ADAPT_PROMPT)

    prompt_path = extract_user_prompt_path(adapt_text)
    if not prompt_path or not prompt_path.exists():
        print(f"ERROR: Could not find user prompt file. Expected path from ADAPT-PROMPT.md")
        print(f"  Extracted: {prompt_path}")
        sys.exit(1)

    user_prompt = read_file(prompt_path)
    print(f"User prompt: {prompt_path.name} ({len(user_prompt)} chars)")

    # Step 3: Generate code
    prompt = build_prompt(task_name, tools_py, user_prompt)
    print(f"\nCalling {MODEL}...")
    print(f"  Prompt: {len(prompt)} chars")

    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text
    usage = response.usage
    print(f"  Response: {len(response_text)} chars")
    print(f"  Tokens: {usage.input_tokens} in, {usage.output_tokens} out")

    # Step 4: Parse and write files
    files = parse_files(response_text)
    if not files:
        print("\nERROR: No files parsed from response. Raw response:")
        print(response_text[:2000])
        sys.exit(1)

    if "task.py" not in files:
        print("\nERROR: No task.py in response. Got: " + ", ".join(files.keys()))
        sys.exit(1)

    print(f"\nWriting {len(files)} files to tools/{task_name}/:")
    for filename, content in files.items():
        filepath = target_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {filename} ({len(content)} chars)")

    # Step 5: Verify
    print(f"\nDone. Run with: python -m tools.{task_name}")


if __name__ == "__main__":
    main()
