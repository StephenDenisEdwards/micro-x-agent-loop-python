"""Shared fixtures for integration tests.

Starts real MCP servers via stdio and provides connected clients
to test functions. Requires credentials in .env or environment.
"""

import os
import importlib.util
from pathlib import Path

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "tools" / "template"
GITHUB_SERVER_JS = REPO_ROOT / "mcp_servers" / "ts" / "packages" / "github" / "dist" / "index.js"


def _load_module(name: str, file_path: Path):
    """Import a Python module from an arbitrary file path."""
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_dotenv():
    """Load .env from repo root (setdefault — won't overwrite existing vars)."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

# Load McpClient from the template app
_mcp_client_mod = _load_module("_test_mcp_client", TEMPLATE_DIR / "mcp_client.py")
McpClient = _mcp_client_mod.McpClient


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def github_mcp():
    """Start the real GitHub MCP server and yield a connected McpClient."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        pytest.skip("GITHUB_TOKEN not set")

    if not GITHUB_SERVER_JS.exists():
        pytest.skip(f"GitHub MCP server not built: {GITHUB_SERVER_JS}")

    client = McpClient("github")
    await client.connect(
        command="node",
        args=[str(GITHUB_SERVER_JS)],
        env={"GITHUB_TOKEN": token},
    )
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def clients(github_mcp):
    """Clients dict as expected by template wrapper functions."""
    return {"github": github_mcp}
