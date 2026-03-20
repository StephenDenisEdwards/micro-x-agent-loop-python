"""Job search tool — collect from Gmail/LinkedIn, score, generate report."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .mcp_client import McpClient
from .collector import collect_jobserve_emails, collect_linkedin_jobs
from .scorer import score_job
from .processor import (
    make_top_10_section,
    make_jobserve_section,
    make_linkedin_section,
    make_summary_section,
    group_jobs_by_category,
)


def load_json_config(config_path: str | None = None) -> tuple[dict, str]:
    """Load application config."""
    if config_path:
        p = Path(config_path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        with open(p) as f:
            return json.load(f), str(p)

    default_path = Path.cwd() / "config.json"
    if not default_path.exists():
        return {}, "config.json (defaults)"

    with open(default_path) as f:
        data = json.load(f)

    config_file = data.get("ConfigFile")
    if config_file:
        target = Path.cwd() / config_file
        if not target.exists():
            raise FileNotFoundError(
                f"ConfigFile target not found: {target} "
                f"(referenced from config.json)"
            )
        with open(target) as f:
            return json.load(f), str(config_file)

    return data, "config.json"


async def connect_all_mcp_servers(
    server_configs: dict[str, dict[str, Any]],
) -> dict[str, McpClient]:
    """Connect to all configured MCP servers in parallel."""
    clients: dict[str, McpClient] = {}
    tasks: dict[str, asyncio.Task] = {}

    for name, cfg in server_configs.items():
        command = cfg.get("command", "")
        args = cfg.get("args", [])
        env = cfg.get("env")
        if not command:
            continue

        client = McpClient(name)
        clients[name] = client
        tasks[name] = asyncio.create_task(client.connect(command, args, env))

    connected: dict[str, McpClient] = {}
    for name, task in tasks.items():
        try:
            await task
            connected[name] = clients[name]
            print(f"  {name}: connected")
        except Exception as ex:
            print(f"  {name}: FAILED ({ex})")

    return connected


async def run_task(clients: dict[str, McpClient], config: dict) -> None:
    """Collect jobs, score, generate report."""
    print("\nCollecting jobs...")

    # Need Gmail and LinkedIn clients
    gmail = clients.get("google")
    linkedin_client = clients.get("linkedin")

    if not gmail:
        print("ERROR: 'google' MCP server required for Gmail")
        return

    # Collect JobServe emails
    print("  Fetching JobServe emails (last 24h)...")
    jobserve_jobs = await collect_jobserve_emails(gmail)
    print(f"    Found {len(jobserve_jobs)} JobServe jobs")

    # Collect LinkedIn jobs
    linkedin_jobs = []
    if linkedin_client:
        print("  Searching LinkedIn...")
        queries = [
            "Senior .NET Developer",
            "Software Architect Azure",
            "AI ML Engineer",
        ]
        linkedin_jobs = await collect_linkedin_jobs(linkedin_client, queries)
        print(f"    Found {len(linkedin_jobs)} LinkedIn jobs")

    all_jobs = jobserve_jobs + linkedin_jobs
    print(f"\nTotal jobs collected: {len(all_jobs)}")

    # Score all jobs
    print("Scoring jobs...")
    scored_jobs = []
    for job in all_jobs:
        score = score_job(job)
        if score >= 5:
            scored_jobs.append((job, score))

    scored_jobs.sort(key=lambda x: x[1], reverse=True)
    print(f"Jobs scoring 5+/10: {len(scored_jobs)}")

    # Separate by source
    jobserve_scored = [j for j in scored_jobs if j[0]["source"] == "jobserve"]
    linkedin_scored = [j for j in scored_jobs if j[0]["source"] == "linkedin"]

    # Generate report
    print("Generating report...")
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = Path.cwd() / f"todays-jobs-{today}.md"

    title = f"# Today's Job Opportunities - {datetime.now().strftime('%B %d, %Y')}\n\n"

    with open(report_file, "w") as f:
        f.write(title)

    # Top 10
    top_10 = make_top_10_section(scored_jobs)
    with open(report_file, "a") as f:
        f.write(top_10)

    # JobServe section
    if jobserve_scored:
        jobserve_section = make_jobserve_section(jobserve_scored)
        with open(report_file, "a") as f:
            f.write(jobserve_section)

    # LinkedIn section
    if linkedin_scored:
        linkedin_section = make_linkedin_section(linkedin_scored)
        with open(report_file, "a") as f:
            f.write(linkedin_section)

    # Summary
    summary_section = make_summary_section(all_jobs, scored_jobs)
    with open(report_file, "a") as f:
        f.write(summary_section)

    print(f"\nReport written to: {report_file}")
    print(f"Top 10 jobs: {len(scored_jobs[:10])}")
    print(f"JobServe: {len(jobserve_scored)}, LinkedIn: {len(linkedin_scored)}")


async def main() -> None:
    load_dotenv()

    config_path = None
    args = sys.argv[1:]
    if "--config" in args:
        idx = args.index("--config")
        if idx + 1 < len(args):
            config_path = args[idx + 1]

    config, source = load_json_config(config_path)
    print(f"Config: {source}")

    # Connect only needed servers
    mcp_configs = config.get("McpServers", {})
    needed = {k: v for k, v in mcp_configs.items() if k in ["google", "linkedin"]}

    if not needed:
        print("\nERROR: No MCP servers configured (need 'google' and optionally 'linkedin')")
        return

    print(f"\nConnecting {len(needed)} MCP servers...")
    clients = await connect_all_mcp_servers(needed)
    print(f"{len(clients)}/{len(needed)} servers connected")

    try:
        await run_task(clients, config)
    finally:
        if clients:
            print("\nShutting down MCP servers...")
            for name, client in clients.items():
                try:
                    await client.close()
                except Exception:
                    pass


def _run() -> None:
    """Windows-safe entry point."""
    _original_hook = sys.unraisablehook

    def _quiet_hook(args) -> None:
        if args.exc_type is ValueError and "closed pipe" in str(args.exc_value):
            return
        if args.exc_type is ResourceWarning and "unclosed transport" in str(args.exc_value):
            return
        _original_hook(args)

    sys.unraisablehook = _quiet_hook
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    _run()
