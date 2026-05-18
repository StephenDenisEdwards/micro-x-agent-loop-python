"""Pytest config for the behavioural eval suite.

Eval tests are skipped by default — they spawn the full MCP server set,
make live LLM calls, and cost money. Run them explicitly with:

    MICRO_X_RUN_EVALS=1 pytest tests/evals/ -v

(`pytest tests/` continues to exclude them automatically.)
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

# Eval construction reads ${ENV} placeholders out of config-base.json and
# needs provider API keys — same as `--run`. Load .env before any test.
load_dotenv()

_RUN_EVALS = os.environ.get("MICRO_X_RUN_EVALS", "").strip().lower() in {"1", "true", "yes", "on"}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "eval: behavioural eval (live LLM + MCP servers; skipped unless MICRO_X_RUN_EVALS=1)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _RUN_EVALS:
        return
    skip = pytest.mark.skip(reason="behavioural eval — set MICRO_X_RUN_EVALS=1 to run")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip)
