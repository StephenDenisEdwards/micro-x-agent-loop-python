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
    if isinstance(result, dict):
        return result.get("messages", [])
    if isinstance(result, str):
        return _parse_gmail_search_text(result)
    return []


async def gmail_read(clients: Clients, message_id: str) -> dict | None:
    """Read full email. Returns {messageId, from, to, date, subject, body} or None.

    The body field is html-to-text converted HTML. Links appear as 'text [url]'.
    Content is positional (visual blocks separated by blank lines), not labeled
    key-value pairs.
    """
    result = await _get(clients, "google").call_tool("gmail_read", {"messageId": message_id})
    if isinstance(result, dict):
        return result
    if isinstance(result, str) and result.strip():
        return _parse_gmail_read_text(message_id, result)
    return None


def _parse_gmail_search_text(text: str) -> list[dict]:
    """Parse gmail_search text format: 'ID: ...\n  Date: ...\n  From: ...' blocks."""
    if not text.strip() or "No emails found" in text:
        return []
    messages: list[dict] = []
    current: dict[str, str] = {}
    for line in text.split("\n"):
        stripped = line.strip()
        if line.startswith("ID: "):
            if current:
                messages.append(current)
            current = {"id": line[4:].strip()}
        elif stripped.startswith("Date: ") and current:
            current["date"] = stripped[6:]
        elif stripped.startswith("From: ") and current:
            current["from"] = stripped[6:]
        elif stripped.startswith("Subject: ") and current:
            current["subject"] = stripped[9:]
        elif stripped.startswith("Snippet: ") and current:
            current["snippet"] = stripped[9:]
    if current:
        messages.append(current)
    return messages


def _parse_gmail_read_text(message_id: str, text: str) -> dict:
    """Parse gmail_read text format: 'From: ...\nTo: ...\nDate: ...\nSubject: ...\n\n<body>'."""
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


async def calendar_get(clients: Clients, event_id: str, calendar_id: str = "primary") -> str:
    """Get a specific calendar event by ID. Returns event details text."""
    result = await _get(clients, "google").call_tool("calendar_get_event", {
        "eventId": event_id, "calendarId": calendar_id,
    })
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


async def contacts_list(clients: Clients, page_size: int = 10,
                        page_token: str | None = None,
                        sort_order: str | None = None) -> str:
    """List contacts. sort_order: 'LAST_MODIFIED_ASCENDING', 'FIRST_NAME_ASCENDING', etc. Returns text."""
    args: dict[str, Any] = {"pageSize": page_size}
    if page_token:
        args["pageToken"] = page_token
    if sort_order:
        args["sortOrder"] = sort_order
    result = await _get(clients, "google").call_tool("contacts_list", args)
    return result if isinstance(result, str) else str(result)


async def contacts_get(clients: Clients, resource_name: str) -> str:
    """Get a contact by resource name (e.g. 'people/c1234567890'). Returns text."""
    result = await _get(clients, "google").call_tool("contacts_get", {
        "resourceName": resource_name,
    })
    return result if isinstance(result, str) else str(result)


async def contacts_create(clients: Clients, given_name: str, family_name: str | None = None,
                           email: str | None = None, email_type: str = "other",
                           phone: str | None = None, phone_type: str = "other",
                           organization: str | None = None, job_title: str | None = None) -> str:
    """Create a contact. Returns status text."""
    args: dict[str, Any] = {"givenName": given_name, "emailType": email_type, "phoneType": phone_type}
    if family_name:
        args["familyName"] = family_name
    if email:
        args["email"] = email
    if phone:
        args["phone"] = phone
    if organization:
        args["organization"] = organization
    if job_title:
        args["jobTitle"] = job_title
    result = await _get(clients, "google").call_tool("contacts_create", args)
    return result if isinstance(result, str) else str(result)


async def contacts_update(clients: Clients, resource_name: str, etag: str,
                           given_name: str | None = None, family_name: str | None = None,
                           email: str | None = None, email_type: str = "other",
                           phone: str | None = None, phone_type: str = "other",
                           organization: str | None = None, job_title: str | None = None) -> str:
    """Update a contact. Requires etag from contacts_get. Returns status text."""
    args: dict[str, Any] = {"resourceName": resource_name, "etag": etag,
                            "emailType": email_type, "phoneType": phone_type}
    if given_name:
        args["givenName"] = given_name
    if family_name:
        args["familyName"] = family_name
    if email:
        args["email"] = email
    if phone:
        args["phone"] = phone
    if organization:
        args["organization"] = organization
    if job_title:
        args["jobTitle"] = job_title
    result = await _get(clients, "google").call_tool("contacts_update", args)
    return result if isinstance(result, str) else str(result)


async def contacts_delete(clients: Clients, resource_name: str) -> str:
    """Delete a contact by resource name. Returns status text."""
    result = await _get(clients, "google").call_tool("contacts_delete", {
        "resourceName": resource_name,
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
                                       batch_size: int = 2, delay: float = 2.0,
                                       **kwargs) -> list[dict]:
    """Search LinkedIn and fetch full details for each result. Returns enriched job dicts.

    Fetches details in small batches with delays to avoid LinkedIn rate limiting (HTTP 429).
    """
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
        if i > 0:
            await asyncio.sleep(delay)
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


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


async def github_list_repos(clients: Clients, owner: str | None = None,
                            type: str = "all", sort: str = "updated",
                            max_results: int = 10) -> list[dict]:
    """List repos for owner (or authenticated user if omitted).

    Returns list of {name, full_name, description, url, language, stars, forks, visibility, updated}.
    """
    args: dict[str, Any] = {"type": type, "sort": sort, "maxResults": max_results}
    if owner:
        args["owner"] = owner
    result = await _get(clients, "github").call_tool("list_repos", args)
    if isinstance(result, dict):
        return result.get("repos", [])
    return []


async def github_get_file(clients: Clients, repo: str, path: str,
                          ref: str | None = None) -> dict:
    """Get file content or directory listing from a repo.

    Returns {type, repo, path, ...} where type is 'file', 'directory', or 'binary'.
    - file: includes 'content' (str) and 'size' (int)
    - directory: includes 'entries' (list of {name, type, size})
    """
    args: dict[str, Any] = {"repo": repo, "path": path}
    if ref:
        args["ref"] = ref
    result = await _get(clients, "github").call_tool("get_file", args)
    if isinstance(result, dict):
        return result
    return {"type": "file", "repo": repo, "path": path, "content": result if isinstance(result, str) else ""}


async def github_search_code(clients: Clients, query: str, repo: str | None = None,
                              language: str | None = None, max_results: int = 10) -> list[dict]:
    """Search code across repos. Returns list of {repo, path, url, fragment}."""
    args: dict[str, Any] = {"query": query, "maxResults": max_results}
    if repo:
        args["repo"] = repo
    if language:
        args["language"] = language
    result = await _get(clients, "github").call_tool("search_code", args)
    if isinstance(result, dict):
        return result.get("results", [])
    return []


async def github_list_prs(clients: Clients, repo: str | None = None,
                          state: str = "open", author: str | None = None,
                          max_results: int = 10) -> list[dict]:
    """List pull requests. If repo omitted, lists your PRs across all repos.

    Returns list of {number, title, author, state, updated, url}.
    """
    args: dict[str, Any] = {"state": state, "maxResults": max_results}
    if repo:
        args["repo"] = repo
    if author:
        args["author"] = author
    result = await _get(clients, "github").call_tool("list_prs", args)
    if isinstance(result, dict):
        return result.get("prs", [])
    return []


async def github_get_pr(clients: Clients, repo: str, number: int) -> dict:
    """Get PR details including diff stats, reviews, CI status.

    Returns {number, title, state, draft, mergeable, author, head, base, created, updated,
    approved_reviews, changes_requested, ci_status, additions, deletions, changed_files, url, body}.
    """
    result = await _get(clients, "github").call_tool("get_pr", {
        "repo": repo, "number": number,
    })
    if isinstance(result, dict):
        return result
    return {"number": number, "title": "", "state": "", "url": ""}


async def github_create_pr(clients: Clients, repo: str, title: str, head: str,
                            body: str | None = None, base: str = "main",
                            draft: bool = False) -> dict:
    """Create a pull request. Returns {number, title, draft, head, base, url}."""
    args: dict[str, Any] = {"repo": repo, "title": title, "head": head, "base": base, "draft": draft}
    if body:
        args["body"] = body
    result = await _get(clients, "github").call_tool("create_pr", args)
    if isinstance(result, dict):
        return result
    return {"number": 0, "title": title, "head": head, "base": base, "url": ""}


async def github_list_issues(clients: Clients, repo: str | None = None,
                              state: str = "open", labels: str | None = None,
                              query: str | None = None, max_results: int = 10) -> list[dict]:
    """List or search issues.

    Returns list of {number, title, author, state, created, comments, labels, url}.
    """
    args: dict[str, Any] = {"state": state, "maxResults": max_results}
    if repo:
        args["repo"] = repo
    if labels:
        args["labels"] = labels
    if query:
        args["query"] = query
    result = await _get(clients, "github").call_tool("list_issues", args)
    if isinstance(result, dict):
        return result.get("issues", [])
    return []


async def github_create_issue(clients: Clients, repo: str, title: str,
                               body: str | None = None, labels: list[str] | None = None,
                               assignees: list[str] | None = None) -> dict:
    """Create an issue. Returns {number, title, url, labels}."""
    args: dict[str, Any] = {"repo": repo, "title": title}
    if body:
        args["body"] = body
    if labels:
        args["labels"] = labels
    if assignees:
        args["assignees"] = assignees
    result = await _get(clients, "github").call_tool("create_issue", args)
    if isinstance(result, dict):
        return result
    return {"number": 0, "title": title, "url": "", "labels": labels or []}


# ---------------------------------------------------------------------------
# Anthropic Admin
# ---------------------------------------------------------------------------


async def anthropic_usage(clients: Clients, action: str, starting_at: str,
                          ending_at: str | None = None, bucket_width: str | None = None,
                          group_by: list[str] | None = None, limit: int | None = None) -> str:
    """Get usage/cost/claude_code report. action: 'usage', 'cost', or 'claude_code'. Returns text."""
    args: dict[str, Any] = {"action": action, "starting_at": starting_at}
    if ending_at:
        args["ending_at"] = ending_at
    if bucket_width:
        args["bucket_width"] = bucket_width
    if group_by:
        args["group_by"] = group_by
    if limit is not None:
        args["limit"] = limit
    result = await _get(clients, "anthropic-admin").call_tool("anthropic_usage", args)
    return result if isinstance(result, str) else str(result)


# ---------------------------------------------------------------------------
# Interview Assist — Analysis
# ---------------------------------------------------------------------------


async def ia_healthcheck(clients: Clients, repo_path: str | None = None) -> str:
    """Check interview-assist project health. Returns status text."""
    args: dict[str, Any] = {}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_healthcheck", args)
    return result if isinstance(result, str) else str(result)


async def ia_list_recordings(clients: Clients, limit: int = 30,
                              repo_path: str | None = None) -> str:
    """List available recordings. Returns text summary."""
    args: dict[str, Any] = {"limit": limit}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_list_recordings", args)
    return result if isinstance(result, str) else str(result)


async def ia_analyze_session(clients: Clients, session_file: str,
                              repo_path: str | None = None,
                              timeout_seconds: int = 900) -> str:
    """Analyze a recording session. Returns analysis report text."""
    args: dict[str, Any] = {"session_file": session_file, "timeout_seconds": timeout_seconds}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_analyze_session", args)
    return result if isinstance(result, str) else str(result)


async def ia_evaluate_session(clients: Clients, session_file: str,
                               output_file: str | None = None, model: str | None = None,
                               ground_truth_file: str | None = None,
                               repo_path: str | None = None,
                               timeout_seconds: int = 1800) -> str:
    """Evaluate session against ground truth. Returns evaluation text."""
    args: dict[str, Any] = {"session_file": session_file, "timeout_seconds": timeout_seconds}
    if output_file:
        args["output_file"] = output_file
    if model:
        args["model"] = model
    if ground_truth_file:
        args["ground_truth_file"] = ground_truth_file
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_evaluate_session", args)
    return result if isinstance(result, str) else str(result)


async def ia_compare_strategies(clients: Clients, session_file: str,
                                 output_file: str | None = None,
                                 repo_path: str | None = None,
                                 timeout_seconds: int = 1800) -> str:
    """Compare detection strategies. Returns comparison text."""
    args: dict[str, Any] = {"session_file": session_file, "timeout_seconds": timeout_seconds}
    if output_file:
        args["output_file"] = output_file
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_compare_strategies", args)
    return result if isinstance(result, str) else str(result)


async def ia_tune_threshold(clients: Clients, session_file: str,
                             optimize: str = "f1",
                             repo_path: str | None = None,
                             timeout_seconds: int = 1800) -> str:
    """Tune detection threshold. optimize: 'f1', 'precision', 'recall', or 'balanced'. Returns text."""
    args: dict[str, Any] = {"session_file": session_file, "optimize": optimize,
                            "timeout_seconds": timeout_seconds}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_tune_threshold", args)
    return result if isinstance(result, str) else str(result)


async def ia_regression_test(clients: Clients, baseline_file: str, data_file: str,
                              repo_path: str | None = None,
                              timeout_seconds: int = 1800) -> str:
    """Run regression test against a baseline. Returns test results text."""
    args: dict[str, Any] = {"baseline_file": baseline_file, "data_file": data_file,
                            "timeout_seconds": timeout_seconds}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_regression_test", args)
    return result if isinstance(result, str) else str(result)


async def ia_create_baseline(clients: Clients, data_file: str, output_file: str,
                              version: str = "1.0",
                              repo_path: str | None = None,
                              timeout_seconds: int = 1800) -> str:
    """Create a baseline from data. Returns baseline text."""
    args: dict[str, Any] = {"data_file": data_file, "output_file": output_file,
                            "version": version, "timeout_seconds": timeout_seconds}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_create_baseline", args)
    return result if isinstance(result, str) else str(result)


async def ia_transcribe_once(clients: Clients, duration_seconds: int = 8,
                              source: str = "microphone",
                              mic_device_id: str | None = None,
                              mic_device_name: str | None = None,
                              sample_rate: int = 16000,
                              model: str = "nova-2", language: str = "en",
                              endpointing_ms: int = 300, utterance_end_ms: int = 1000,
                              diarize: bool = False, output_file: str | None = None,
                              repo_path: str | None = None,
                              timeout_seconds: int = 180) -> str:
    """One-shot transcription. source: 'microphone' or 'loopback'. Returns transcription text."""
    args: dict[str, Any] = {
        "duration_seconds": duration_seconds, "source": source,
        "sample_rate": sample_rate, "model": model, "language": language,
        "endpointing_ms": endpointing_ms, "utterance_end_ms": utterance_end_ms,
        "diarize": diarize, "timeout_seconds": timeout_seconds,
    }
    if mic_device_id:
        args["mic_device_id"] = mic_device_id
    if mic_device_name:
        args["mic_device_name"] = mic_device_name
    if output_file:
        args["output_file"] = output_file
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("ia_transcribe_once", args)
    return result if isinstance(result, str) else str(result)


# ---------------------------------------------------------------------------
# Interview Assist — STT Sessions
# ---------------------------------------------------------------------------


async def stt_list_devices(clients: Clients, repo_path: str | None = None) -> str:
    """List audio input devices. Returns device info text."""
    args: dict[str, Any] = {}
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("stt_list_devices", args)
    return result if isinstance(result, str) else str(result)


async def stt_start_session(clients: Clients, source: str = "microphone",
                             mic_device_id: str | None = None,
                             mic_device_name: str | None = None,
                             model: str = "nova-2", language: str = "en",
                             sample_rate: int = 16000,
                             endpointing_ms: int = 300, utterance_end_ms: int = 1000,
                             diarize: bool = False, chunk_seconds: int = 4,
                             repo_path: str | None = None) -> str:
    """Start a live STT session. Returns session_id and status text."""
    args: dict[str, Any] = {
        "source": source, "model": model, "language": language,
        "sample_rate": sample_rate, "endpointing_ms": endpointing_ms,
        "utterance_end_ms": utterance_end_ms, "diarize": diarize,
        "chunk_seconds": chunk_seconds,
    }
    if mic_device_id:
        args["mic_device_id"] = mic_device_id
    if mic_device_name:
        args["mic_device_name"] = mic_device_name
    if repo_path:
        args["repo_path"] = repo_path
    result = await _get(clients, "interview-assist").call_tool("stt_start_session", args)
    return result if isinstance(result, str) else str(result)


async def stt_get_updates(clients: Clients, session_id: str,
                           since_seq: int = 0, limit: int = 100) -> str:
    """Get transcript updates since a sequence number. Returns events text."""
    result = await _get(clients, "interview-assist").call_tool("stt_get_updates", {
        "session_id": session_id, "since_seq": since_seq, "limit": limit,
    })
    return result if isinstance(result, str) else str(result)


async def stt_get_session(clients: Clients, session_id: str) -> str:
    """Get STT session status and metadata. Returns session info text."""
    result = await _get(clients, "interview-assist").call_tool("stt_get_session", {
        "session_id": session_id,
    })
    return result if isinstance(result, str) else str(result)


async def stt_stop_session(clients: Clients, session_id: str) -> str:
    """Stop a live STT session. Returns final status text."""
    result = await _get(clients, "interview-assist").call_tool("stt_stop_session", {
        "session_id": session_id,
    })
    return result if isinstance(result, str) else str(result)
