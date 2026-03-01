"""Data collection orchestration for Gmail (JobServe) and LinkedIn job searches."""

import asyncio
import logging
from typing import Any

from .mcp_client import McpClient

logger = logging.getLogger(__name__)


async def collect_jobserve_emails(google_client: McpClient) -> list[dict[str, Any]]:
    """Search Gmail for JobServe emails from the last 24 hours and read each one."""
    print("  Searching Gmail for JobServe emails (last 24h)...")
    result = await google_client.call_tool(
        "gmail_search",
        {"query": "from:jobserve.com newer_than:1d", "maxResults": 15},
    )

    # structuredContent: { messages: [...], total_found: N }
    # Falls back to text string when no emails found
    if isinstance(result, str):
        print("  No JobServe emails found in last 24 hours.")
        return []

    messages = result.get("messages", [])
    if not messages:
        print("  No JobServe emails found in last 24 hours.")
        return []

    print(f"  Found {len(messages)} JobServe emails. Reading full content...")
    jobs = []
    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue
        try:
            # structuredContent: { messageId, from, to, date, subject, body }
            email = await google_client.call_tool("gmail_read", {"messageId": msg_id})
            if isinstance(email, dict):
                email["source"] = "jobserve"
                jobs.append(email)
            else:
                jobs.append({"source": "jobserve", "messageId": msg_id, "body": email})
        except Exception as e:
            logger.warning("Failed to read email %s: %s", msg_id, e)

    print(f"  Read {len(jobs)} JobServe email(s).")
    return jobs


async def collect_linkedin_jobs(linkedin_client: McpClient) -> list[dict[str, Any]]:
    """Run multiple LinkedIn job searches, deduplicate, and fetch details."""
    searches = [
        {
            "keyword": ".NET Azure",
            "location": "United Kingdom",
            "jobType": "contract",
            "dateSincePosted": "past week",
            "experienceLevel": "senior",
            "limit": 15,
            "sortBy": "recent",
        },
        {
            "keyword": "Software Architect C#",
            "location": "United Kingdom",
            "dateSincePosted": "past week",
            "experienceLevel": "senior",
            "limit": 15,
            "sortBy": "recent",
        },
        {
            "keyword": "AI ML Engineer",
            "location": "United Kingdom",
            "dateSincePosted": "past week",
            "experienceLevel": "senior",
            "limit": 10,
            "sortBy": "recent",
        },
    ]

    # Run all searches
    all_results: list[dict[str, Any]] = []
    for search in searches:
        keyword = search["keyword"]
        print(f"  LinkedIn search: '{keyword}'...")
        try:
            # structuredContent: { jobs: [...], total_found: N }
            result = await linkedin_client.call_tool("linkedin_jobs", search)
            if isinstance(result, str):
                print(f"    No results for '{keyword}'.")
                continue

            jobs_list = result.get("jobs", [])
            print(f"    Found {len(jobs_list)} jobs for '{keyword}'.")
            all_results.extend(jobs_list)
        except Exception as e:
            logger.warning("LinkedIn search failed for '%s': %s", keyword, e)
            print(f"    Search failed for '{keyword}': {e}")

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_jobs: list[dict[str, Any]] = []
    for job in all_results:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_jobs.append(job)

    print(f"  {len(unique_jobs)} unique LinkedIn jobs after deduplication (from {len(all_results)} total).")

    if not unique_jobs:
        return []

    # Fetch details concurrently
    print(f"  Fetching details for {len(unique_jobs)} jobs...")

    async def fetch_detail(job: dict[str, Any]) -> dict[str, Any]:
        url = job.get("url", "")
        if not url:
            return {**job, "source": "linkedin", "detail": {}}
        try:
            # structuredContent: { title, company, location, description, url }
            detail = await linkedin_client.call_tool("linkedin_job_detail", {"url": url})
            if isinstance(detail, dict):
                return {**job, "source": "linkedin", "detail": detail}
            return {**job, "source": "linkedin", "detail": {"description": detail}}
        except Exception as e:
            logger.warning("Failed to fetch detail for %s: %s", url, e)
            return {**job, "source": "linkedin", "detail": {"error": str(e)}}

    batch_size = 5
    detailed_jobs: list[dict[str, Any]] = []
    for i in range(0, len(unique_jobs), batch_size):
        batch = unique_jobs[i : i + batch_size]
        results = await asyncio.gather(*(fetch_detail(job) for job in batch))
        detailed_jobs.extend(results)
        if i + batch_size < len(unique_jobs):
            print(f"    Fetched {len(detailed_jobs)}/{len(unique_jobs)} details...")

    print(f"  Collected details for {len(detailed_jobs)} LinkedIn jobs.")
    return detailed_jobs
