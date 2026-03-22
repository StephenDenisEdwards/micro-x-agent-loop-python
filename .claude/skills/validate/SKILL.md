---
name: validate
description: Run the full validation suite (tests, linting, type checking) and summarise results.
---

# Validate

Run all project quality checks and provide a concise summary.

## Prerequisites

Before running any checks, ensure the virtual environment is ready:

1. Run `.venv/Scripts/python -c "import pytest" 2>&1` (Windows) or `.venv/bin/python -c "import pytest" 2>&1` (Unix) to verify dev dependencies are installed.
2. If the import fails, run `.venv/Scripts/pip install -e ".[dev]"` (or `.venv/bin/pip`) first.
3. Always use the venv Python (`.venv/Scripts/python` / `.venv/bin/python`), never bare `python`.

## Steps

1. **Tests**: Run `.venv/Scripts/python -m pytest tests/ -v` and capture results.

2. **Lint**: Run `.venv/Scripts/python -m ruff check src/ tests/` and capture results.

3. **Type check**: Run `.venv/Scripts/python -m mypy src/` and capture results.

IMPORTANT: Run all three checks **sequentially**, not in parallel. When parallel Bash tool calls are used and one exits with a non-zero code, Claude Code cancels the remaining calls. Since test failures (exit code 1) are expected and informative, sequential execution ensures all three checks always complete.

## Output

Summarise results in this format:

```
Tests:      ✓ X passed / ✗ Y failed / ⊘ Z skipped
Lint:       ✓ clean / ✗ N issues
Type check: ✓ clean / ✗ N errors
```

If any check fails, list the specific failures concisely (file, line, message) so they can be acted on immediately.

## Options

If `$ARGUMENTS` contains:
- `tests` or `test` — run only pytest
- `lint` — run only ruff
- `types` or `mypy` — run only mypy
- No arguments — run all three
