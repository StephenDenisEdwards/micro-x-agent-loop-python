"""Job search console app — cheap mode.

Hardcodes orchestration logic, calls MCP servers directly, and uses a single
Haiku API call for scoring/report generation.

Usage: python -m tools.job_search
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .collector import collect_jobserve_emails, collect_linkedin_jobs
from .mcp_client import McpClient
from .scorer import score_and_report

# MCP server paths (from config-standard-no-summarization.json)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MCP_SERVERS = PROJECT_ROOT / "mcp_servers" / "ts" / "packages"

# External file paths
RESOURCES_DIR = Path(r"C:\Users\steph\source\repos\resources\documents")
CRITERIA_FILE = RESOURCES_DIR / "job-search-criteria.txt"
PROMPT_FILE = PROJECT_ROOT / "documentation" / "docs" / "examples" / "job-search-prompt.txt"


async def main() -> None:
    load_dotenv()

    today_iso = date.today().isoformat()
    output_file = RESOURCES_DIR / f"todays-jobs-{today_iso}.md"

    print(f"Job Search — {date.today().strftime('%B %d, %Y')}")
    print("=" * 50)

    # Load criteria and prompt template
    print("\nLoading search criteria and prompt template...")
    criteria = CRITERIA_FILE.read_text(encoding="utf-8")
    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")

    # Connect MCP servers
    google = McpClient("google")
    linkedin = McpClient("linkedin")

    try:
        print("\nConnecting MCP servers...")
        print("  Starting Google MCP server...")
        await google.connect(
            command="node",
            args=[str(MCP_SERVERS / "google" / "dist" / "index.js")],
        )
        print("  Google MCP server connected.")

        print("  Starting LinkedIn MCP server...")
        await linkedin.connect(
            command="node",
            args=[str(MCP_SERVERS / "linkedin" / "dist" / "index.js")],
        )
        print("  LinkedIn MCP server connected.")

        # Collect data
        print("\nCollecting job data...")
        print("\n[Gmail / JobServe]")
        jobserve_jobs = await collect_jobserve_emails(google)

        print("\n[LinkedIn]")
        linkedin_jobs = await collect_linkedin_jobs(linkedin)

        total_jobs = len(jobserve_jobs) + len(linkedin_jobs)
        print(f"\nTotal jobs collected: {total_jobs} ({len(jobserve_jobs)} JobServe + {len(linkedin_jobs)} LinkedIn)")

        if total_jobs == 0:
            print("\nNo jobs found. Exiting.")
            return

        # Score and generate report
        print("\nScoring jobs and generating report (single Haiku API call)...")
        report = await score_and_report(jobserve_jobs, linkedin_jobs, criteria, prompt_template)

        # Write output
        output_file.write_text(report, encoding="utf-8")
        print(f"\nReport written to: {output_file}")
        print(f"Report length: {len(report):,} characters")

    finally:
        print("\nShutting down MCP servers...")
        await google.close()
        await linkedin.close()
        print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
