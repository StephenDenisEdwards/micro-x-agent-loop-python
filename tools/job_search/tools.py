"""Typed wrappers for MCP tools. Each function knows its server, handles errors, and returns parsed data."""

import asyncio
from typing import Any

# Type alias for the clients dict passed around
Clients = dict[str, Any]  # {"google": McpClient, "linkedin": McpClient, ...}


def _get(clients: Clients, server: str) -> Any:
    client = clients.get(server)
    if not client:
        raise RuntimeError(f"MCP server '{server}' not connected")
    return client


# ---------------------------------------------------------------------------
# Google — Gmail
# ---------------------------------------------------------------------------


async def gmail_search(clients: Clients, query: str, max_results: int = 10) -> list[dict]:
    """Search Gmail. Returns list of {id, date, from, subject, snippet}."""
    result = await _get(clients, "google").call_tool("gmail_search", {
        "query": query, "maxResults": max_results,
    })
    if isinstance(result, str):
        return []
    return result.get("messages", [])


async def gmail_read(clients: Clients, message_id: str) -> dict | None:
    """Read full email. Returns {messageId, from, to, date, subject, body} or None."""
    result = await _get(clients, "google").call_tool("gmail_read", {"messageId": message_id})
    if isinstance(result, dict):
        return result
    if isinstance(result, str) and result.strip():
        return _parse_gmail_text(message_id, result)
    return None


def _parse_gmail_text(message_id: str, text: str) -> dict:
    """Parse the plain-text format returned when structuredContent is unavailable.

    Format: From: ...\nTo: ...\nDate: ...\nSubject: ...\n\n<body>
    """
    headers: dict[str, str] = {}
    lines = text.split("\n")
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "":
            body_start = i + 1
            break
        for key in ("From", "To", "Date", "Subject"):
            if line.startswith(f"{key}: "):
                headers[key.lower()] = line[len(key) + 2:]
                break
    body = "\n".join(lines[body_start:]).strip()
    return {
        "messageId": message_id,
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "subject": headers.get("subject", ""),
        "body": body,
    }


async def gmail_send(clients: Clients, to: str, subject: str, body: str) -> str:
    """Send an email. Returns status text."""
    result = await _get(clients, "google").call_tool("gmail_send", {
        "to": to, "subject": subject, "body": body,
    })
    return result if isinstance(result, str) else str(result)


# ---------------------------------------------------------------------------
# Google — Calendar
# ---------------------------------------------------------------------------


async def calendar_list(clients: Clients, time_min: str | None = None, time_max: str | None = None,
                        query: str | None = None, max_results: int = 10) -> str:
    """List calendar events. Returns text summary."""
    args: dict[str, Any] = {"maxResults": max_results}
    if time_min:
        args["timeMin"] = time_min
    if time_max:
        args["timeMax"] = time_max
    if query:
        args["query"] = query
    result = await _get(clients, "google").call_tool("calendar_list_events", args)
    return result if isinstance(result, str) else str(result)


async def calendar_create(clients: Clients, summary: str, start: str, end: str,
                          description: str | None = None, location: str | None = None) -> str:
    """Create a calendar event. Returns status text."""
    args: dict[str, Any] = {"summary": summary, "start": start, "end": end}
    if description:
        args["description"] = description
    if location:
        args["location"] = location
    result = await _get(clients, "google").call_tool("calendar_create_event", args)
    return result if isinstance(result, str) else str(result)


# ---------------------------------------------------------------------------
# Google — Contacts
# ---------------------------------------------------------------------------


async def contacts_search(clients: Clients, query: str, max_results: int = 10) -> str:
    """Search contacts. Returns text summary."""
    result = await _get(clients, "google").call_tool("contacts_search", {
        "query": query, "pageSize": max_results,
    })
    return result if isinstance(result, str) else str(result)


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


async def linkedin_search(clients: Clients, keyword: str, location: str = "United Kingdom",
                          date_posted: str = "past week", job_type: str | None = None,
                          experience: str = "senior", limit: int = 10,
                          sort_by: str = "recent") -> list[dict]:
    """Search LinkedIn jobs. Returns list of {index, title, company, location, posted, salary, url}."""
    args: dict[str, Any] = {
        "keyword": keyword, "location": location,
        "dateSincePosted": date_posted, "experienceLevel": experience,
        "limit": limit, "sortBy": sort_by,
    }
    if job_type:
        args["jobType"] = job_type
    result = await _get(clients, "linkedin").call_tool("linkedin_jobs", args)
    if isinstance(result, str):
        return []
    return result.get("jobs", [])


async def linkedin_detail(clients: Clients, url: str) -> dict | None:
    """Fetch full job description. Returns {title, company, location, description, url} or None."""
    result = await _get(clients, "linkedin").call_tool("linkedin_job_detail", {"url": url})
    if isinstance(result, str):
        return None
    return result


async def linkedin_search_with_details(clients: Clients, keyword: str, limit: int = 10,
                                       batch_size: int = 5, **kwargs) -> list[dict]:
    """Search LinkedIn and fetch full details for each result. Returns enriched job dicts."""
    jobs = await linkedin_search(clients, keyword=keyword, limit=limit, **kwargs)
    if not jobs:
        return []

    async def _fetch(job: dict) -> dict:
        url = job.get("url", "")
        if not url:
            return {**job, "detail": {}}
        detail = await linkedin_detail(clients, url)
        return {**job, "detail": detail or {}}

    enriched: list[dict] = []
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]
        results = await asyncio.gather(*(_fetch(j) for j in batch))
        enriched.extend(results)

    return enriched


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


async def web_search(clients: Clients, query: str, count: int = 5) -> list[dict]:
    """Search the web. Returns list of {title, url, description}."""
    result = await _get(clients, "web").call_tool("web_search", {
        "query": query, "count": count,
    })
    if isinstance(result, str):
        return []
    return result.get("results", [])


async def web_fetch(clients: Clients, url: str, max_chars: int = 50000) -> dict | None:
    """Fetch a URL. Returns {url, content, content_length, ...} or None."""
    result = await _get(clients, "web").call_tool("web_fetch", {
        "url": url, "maxChars": max_chars,
    })
    if isinstance(result, str):
        return None
    return result


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


async def fs_read(clients: Clients, path: str) -> str | None:
    """Read a file. Returns content string or None."""
    result = await _get(clients, "filesystem").call_tool("read_file", {"path": path})
    if isinstance(result, str):
        return result
    return result.get("content")


async def fs_write(clients: Clients, path: str, content: str) -> bool:
    """Write a file. Returns True on success."""
    result = await _get(clients, "filesystem").call_tool("write_file", {
        "path": path, "content": content,
    })
    if isinstance(result, dict):
        return result.get("success", False)
    return False


async def fs_bash(clients: Clients, command: str) -> dict:
    """Run a shell command. Returns {stdout, stderr, exit_code}."""
    result = await _get(clients, "filesystem").call_tool("bash", {"command": command})
    if isinstance(result, str):
        return {"stdout": result, "stderr": "", "exit_code": 0}
    return result
