"""Task definition — REPLACE THIS FILE with your own logic."""

from typing import Any

# Which MCP servers to connect (filtered from config automatically).
# Available: google, linkedin, web, filesystem, github, anthropic-admin, interview-assist
SERVERS = ["google", "linkedin", "web", "filesystem", "github", "anthropic-admin", "interview-assist"]


async def run_task(clients: dict[str, Any], config: dict) -> None:
    """Placeholder — replace with your collect → score → report logic."""
    print("\n[Task placeholder]")
    print("Replace task.py with your own logic.")
    print(f"Connected servers: {list(clients.keys())}")
