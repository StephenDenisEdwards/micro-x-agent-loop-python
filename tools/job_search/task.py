import asyncio
from datetime import datetime

from .collector import fetch_jobserve_emails, fetch_linkedin_jobs
from .scorer import score_job
from .processor import build_report
from .utils import write_file, append_file

SERVERS = ["google", "linkedin"]


async def run_task(clients: dict, config: dict) -> None:
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    filename = f"todays-jobs-{date_str}.md"

    print("\nFetching JobServe emails...")
    jobserve_jobs = await fetch_jobserve_emails(clients, config)
    print(f"  Found {len(jobserve_jobs)} JobServe jobs")

    print("Fetching LinkedIn jobs...")
    linkedin_jobs = await fetch_linkedin_jobs(clients, config)
    print(f"  Found {len(linkedin_jobs)} LinkedIn jobs")

    for job in jobserve_jobs:
        job["score"] = score_job(job)

    for job in linkedin_jobs:
        job["score"] = score_job(job)

    jobserve_scored = [j for j in jobserve_jobs if j["score"] >= 5]
    linkedin_scored = [j for j in linkedin_jobs if j["score"] >= 5]

    jobserve_scored.sort(key=lambda x: x["score"], reverse=True)
    linkedin_scored.sort(key=lambda x: x["score"], reverse=True)

    total = len(jobserve_scored) + len(linkedin_scored)
    print(f"\nScoring: {total} jobs scoring 5+ (JobServe: {len(jobserve_scored)}, LinkedIn: {len(linkedin_scored)})")

    sections = build_report(jobserve_scored, linkedin_scored, today)

    output_path = write_file(filename, sections[0], config)
    for section in sections[1:]:
        append_file(filename, section, config)

    print(f"Report written: {output_path}")