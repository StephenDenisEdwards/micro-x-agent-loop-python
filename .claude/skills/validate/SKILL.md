---
name: validate
description: Run the full validation suite (tests, linting, type checking) and summarise results.
---

# Validate

Run all project quality checks and provide a concise summary.

## Steps

1. **Tests**: Run `python -m pytest tests/ -v` and capture results.

2. **Lint**: Run `ruff check src/ tests/` and capture results.

3. **Type check**: Run `mypy src/` and capture results.

Run all three in parallel where possible.

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
