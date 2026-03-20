"""Collect jobs from Gmail (JobServe) and LinkedIn."""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .mcp_client import McpClient


async def collect_jobserve_emails(client: McpClient) -> list[dict[str, Any]]:
    """Fetch JobServe emails from last 24 hours, read full content."""
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(hours=24)
    date_str = yesterday.strftime("%Y/%m/%d")

    result = await client.call_tool("gmail_search", {
        "query": f"from:jobserve@* after:{date_str}",
        "maxResults": 50,
    })

    if isinstance(result, str):
        return []

    messages = result.get("messages", [])
    jobs = []

    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue

        full = await client.call_tool("gmail_read", {"messageId": msg_id})
        if isinstance(full, str):
            continue

        body = full.get("body", "")
        subject = full.get("subject", "")

        job_dict = {
            "source": "jobserve",
            "id": msg_id,
            "subject": subject,
            "body": body,
            "from": full.get("from", ""),
            "date": msg.get("date", ""),
            "raw_email": full,
        }
        jobs.append(job_dict)

    return jobs


async def collect_linkedin_jobs(client: McpClient, queries: list[str]) -> list[dict[str, Any]]:
    """Search LinkedIn with multiple queries, fetch full details."""
    all_jobs = {}

    for query in queries:
        result = await client.call_tool("linkedin_jobs", {
            "keyword": query,
            "location": "Remote",
            "remoteFilter": "remote",
            "dateSincePosted": "past week",
            "limit": 20,
        })

        if isinstance(result, str):
            continue

        jobs_list = result.get("jobs", [])
        for job in jobs_list:
            url = job.get("url", "")
            if url and url not in all_jobs:
                all_jobs[url] = job

    # Deduplicate and fetch full details in batches
    jobs_to_detail = list(all_jobs.values())
    detailed_jobs = []

    for i in range(0, len(jobs_to_detail), 5):
        batch = jobs_to_detail[i : i + 5]
        tasks = [
            fetch_linkedin_detail(client, job) for job in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        detailed_jobs.extend([r for r in results if isinstance(r, dict)])

    return detailed_jobs


async def fetch_linkedin_detail(
    client: McpClient, job: dict[str, Any]
) -> dict[str, Any]:
    """Fetch full LinkedIn job details by URL."""
    url = job.get("url", "")
    if not url:
        return job

    try:
        result = await client.call_tool("linkedin_job_detail", {"url": url})
        if isinstance(result, str):
            return job

        job["description"] = result.get("description", "")
        job["full_title"] = result.get("title", job.get("title", ""))
        job["full_company"] = result.get("company", job.get("company", ""))
        job["full_location"] = result.get("location", job.get("location", ""))
        return job
    except Exception:
        return job
