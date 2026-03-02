import re
from .tools import (
    gmail_search, gmail_read,
    linkedin_search_with_details,
)

JOBSERVE_QUERY = "from:jobserve.com newer_than:7d"

LINKEDIN_KEYWORDS = [
    "AI Agent Engineer",
    "LLM Engineer",
    "AI Architect Python",
    ".NET AI Engineer",
    "Azure AI Engineer",
]

LOCATION = "United Kingdom"


async def fetch_jobserve_emails(clients: dict, config: dict) -> list[dict]:
    messages = await gmail_search(clients, JOBSERVE_QUERY, max_results=50)
    if not messages:
        return []

    jobs = []
    for msg in messages:
        full = await gmail_read(clients, msg["id"])
        if not full:
            continue
        parsed = _parse_jobserve_email(full)
        if parsed:
            jobs.append(parsed)
    return jobs


def _parse_jobserve_email(email: dict) -> dict | None:
    """Parse a JobServe alert email.

    The html-to-text conversion produces a consistent positional format:
        TITLE IN CAPS [job-url]
        (blank)
        LOCATION
        (blank)
        RATE LINE (may include IR35)
        (blank)
        CONTRACT—DURATION
        (blank)
        description text...
        Apply [apply-url]
        More jobs like this [url]
        Employment Business: agency
        Ref: refcode
        Posted: date
        (footer boilerplate)
    """
    body = email.get("body", "") or ""
    subject = email.get("subject", "") or ""
    from_addr = email.get("from", "") or ""
    date = email.get("date", "") or ""

    # Strip footer boilerplate (everything from "This job matches" onwards)
    content = re.split(r"\nThis job matches your saved search", body, maxsplit=1)[0]

    # Split into non-blank "blocks" (lines separated by blank lines)
    header_blocks = _extract_header_blocks(content)

    # Block 0: TITLE [job-url]
    title_block = header_blocks[0] if len(header_blocks) > 0 else ""
    title, job_url = _parse_title_line(title_block)
    if not title:
        title = _clean_subject(subject)
    # JobServe titles are ALL CAPS — convert to title case
    if title.isupper():
        title = title.title()

    # Block 1: LOCATION
    location = header_blocks[1] if len(header_blocks) > 1 else ""

    # Block 2: RATE (may contain IR35)
    rate_block = header_blocks[2] if len(header_blocks) > 2 else ""
    rate_str, rate_daily = _parse_rate(rate_block)
    ir35 = _parse_ir35(rate_block)

    # Block 3: CONTRACT + DURATION
    duration_block = header_blocks[3] if len(header_blocks) > 3 else ""
    duration = _parse_duration(duration_block)

    # If IR35 wasn't in the rate block, check duration block and full body
    if ir35 == "Unknown":
        ir35 = _parse_ir35(duration_block)
    if ir35 == "Unknown":
        ir35 = _parse_ir35(content)

    # Apply URL: "Apply [url]"
    apply_url = ""
    m = re.search(r"Apply\s*\[([^\]]+)\]", content)
    if m:
        apply_url = m.group(1).strip()

    # Agency: "Employment Business: ..."
    agency = ""
    m = re.search(r"Employment Business:\s*(.+)", content)
    if m:
        agency = m.group(1).strip()
    if not agency:
        agency = from_addr

    # Ref: "Ref: ..."
    ref = ""
    m = re.search(r"Ref:\s*(.+)", content)
    if m:
        ref = m.group(1).strip()

    # Description: everything after the header blocks, before Apply
    description = _extract_description(content)

    skills = _extract_skills(content)

    return {
        "source": "jobserve",
        "title": title.strip(),
        "location": _location_from_text(location),
        "rate_str": rate_str,
        "rate_daily": rate_daily,
        "duration": duration,
        "ir35": ir35,
        "agency": agency.strip(),
        "ref": ref.strip(),
        "job_url": job_url.strip(),
        "apply_url": apply_url or job_url.strip(),
        "links": [u for u in [job_url.strip(), apply_url.strip()] if u],
        "skills": skills,
        "sector": "",
        "date": date.strip(),
        "body": description,
        "subject": subject,
    }


def _extract_header_blocks(content: str) -> list[str]:
    """Extract the first few non-blank text blocks from the email body.

    JobServe emails start with a header area where each field is separated
    by one or more blank lines. Returns up to 5 blocks.
    """
    blocks: list[str] = []
    current_lines: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped:
            current_lines.append(stripped)
        elif current_lines:
            blocks.append(" ".join(current_lines))
            current_lines = []
            if len(blocks) >= 5:
                break
    if current_lines and len(blocks) < 5:
        blocks.append(" ".join(current_lines))
    return blocks


def _parse_title_line(block: str) -> tuple[str, str]:
    """Extract title and job URL from the first header block.

    Format: TITLE TEXT [https://jobserve.com/...]
    """
    m = re.match(r"(.+?)\s*\[(https?://[^\]]+)\]", block)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return block, ""


def _clean_subject(subject: str) -> str:
    """Extract job title from email subject like '"Title Here" job alert'."""
    m = re.match(r'"(.+?)"\s*job alert', subject, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return subject.replace(" job alert", "").strip()


def _extract_description(content: str) -> str:
    """Extract the description body, stripping header and footer."""
    # Skip past the header blocks (first ~8 non-blank lines with blanks between)
    lines = content.split("\n")
    blank_count = 0
    desc_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            blank_count += 1
        else:
            blank_count = 0
        # After 4+ header blocks separated by blanks, the description begins
        # when we see a non-ALL-CAPS line after several blanks
        if blank_count >= 2 and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and not next_line.isupper() and not next_line.startswith("CONTRACT"):
                desc_start = i + 1
                break

    # End before "Apply [url]"
    desc_end = len(lines)
    for i in range(desc_start, len(lines)):
        if re.match(r"Apply\s*\[", lines[i].strip()):
            desc_end = i
            break

    return "\n".join(lines[desc_start:desc_end]).strip()


def _parse_rate(text: str) -> tuple[str, int]:
    """Extract rate string and daily rate from a rate line.

    Handles: "£550.00 PER DAY", "UP TO £700 PER DAY", "£550 - £700 PER DAY",
             "£600P/D", "£110,000 PER ANNUM", "£600 - £650 PER DAY INSIDE IR35"
    Returns (display_string, daily_rate_int).
    """
    if not text:
        return ("", 0)

    # Find all £ amounts in the text
    amounts = re.findall(r"£([\d,]+(?:\.\d+)?)", text)
    if not amounts:
        return ("", 0)

    values = [int(a.replace(",", "").split(".")[0]) for a in amounts]

    is_annual = bool(re.search(r"per\s*annum|p\.?a\.?|\bpa\b", text, re.IGNORECASE))
    is_daily = bool(re.search(r"per\s*day|p/?d|\bpd\b|/day", text, re.IGNORECASE))

    if is_annual or (values[0] >= 30000):
        # Annual salary — convert to daily (÷ 220 working days)
        avg = sum(values) // len(values)
        daily = avg // 220
        label = f"£{avg:,} pa (≈£{daily}/day)"
        return (label, daily)

    if len(values) == 2:
        # Range: £550 - £700
        daily = (values[0] + values[1]) // 2
        label = f"£{values[0]} - £{values[1]} per day"
        return (label, daily)

    daily = values[0]
    label = f"£{daily} per day"
    return (label, daily)


def _parse_ir35(text: str) -> str:
    """Extract IR35 status from text."""
    if re.search(r"outside\s+ir35", text, re.IGNORECASE):
        return "Outside IR35"
    if re.search(r"inside\s+ir35", text, re.IGNORECASE):
        return "Inside IR35"
    return "Unknown"


def _parse_duration(text: str) -> str:
    """Extract contract duration from text like 'CONTRACT—6 MONTHS +' or '12 MONTHS'."""
    m = re.search(r"(\d+)\s*months?", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)} months"
    m = re.search(r"(\d+)\s*weeks?", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)} weeks"
    return "Unknown"


def _location_from_text(text: str) -> str:
    """Normalise location text."""
    text = text.strip()
    if not text:
        return "UK"
    if re.search(r"\bremote\b", text, re.IGNORECASE):
        return "Remote"
    if re.search(r"\blondon\b", text, re.IGNORECASE):
        return "London"
    return text.title() if text.isupper() else text


def _extract(text: str, patterns: list[str]) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip() if m.lastindex else m.group(0).strip()
    return ""


AI_SKILLS = [
    "llm", "langchain", "openai", "anthropic", "claude", "gpt", "agent",
    "rag", "vector", "faiss", "embedding", "prompt", "mcp", "tool use",
    "function calling", "huggingface", "transformers", "fine.?tun",
    "tensorflow", "pytorch", "torch", "ml", "machine learning",
    "deep learning", "nlp", "whisper", "speech", "computer vision", "opencv",
    "azure openai", "azure ai", "copilot", "semantic kernel",
]

TECH_SKILLS = [
    "python", r"\.net", "c#", "typescript", "node", "react", "angular",
    "blazor", "azure", "aws", "gcp", "docker", "kubernetes", "fastapi",
    "django", "flask", "sql", "postgres", "mongodb", "cosmos", "redis",
    "microservices", "grpc", "rest", "api", "devops", "ci/cd",
    "clean architecture", "ddd", "cqrs", "event sourcing",
    "hl7", "fhir", "dicom", "healthcare",
]


def _extract_skills(text: str) -> list[str]:
    found = []
    all_skills = AI_SKILLS + TECH_SKILLS
    for skill in all_skills:
        if re.search(skill, text, re.IGNORECASE):
            clean = skill.replace(r"\.", ".").replace("?", "").replace(".", "").strip()
            found.append(clean)
    return list(dict.fromkeys(found))


async def fetch_linkedin_jobs(clients: dict, config: dict) -> list[dict]:
    all_jobs = []
    seen_urls = set()

    for keyword in LINKEDIN_KEYWORDS:
        jobs = await linkedin_search_with_details(
            clients,
            keyword=keyword,
            limit=8,
            batch_size=4,
            location=LOCATION,
            date_posted="past week",
            experience="senior",
            sort_by="recent",
        )
        for job in jobs:
            url = job.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_jobs.append(_normalise_linkedin(job))

    return all_jobs


def _normalise_linkedin(job: dict) -> dict:
    detail = job.get("detail", {})
    description = detail.get("description", "") or job.get("snippet", "") or ""
    skills = _extract_skills(description)

    working_pattern = _extract(description, [
        r"(Remote|Hybrid|On.?site|On\s*site|London|UK Wide)[^\n\r]*",
    ]) or job.get("location", "")

    contract_type = _extract(description, [
        r"(Contract|Permanent|Fixed.?Term|Freelance|Inside IR35|Outside IR35)[^\n\r]*",
    ]) or ""

    ir35 = ""
    if re.search(r"outside ir35", description, re.IGNORECASE):
        ir35 = "Outside IR35"
    elif re.search(r"inside ir35", description, re.IGNORECASE):
        ir35 = "Inside IR35"

    rate = _extract(description, [
        r"£[\d,]+\s*(?:per day|pd|p/d|/day|/d|per annum|pa|k)?(?:\s*[-–]\s*£[\d,]+)?[^\n\r]*",
        r"Rate[:\s]+([^\n\r]+)",
    ]) or ""

    sector = _extract(description, [
        r"Sector[:\s]+([^\n\r]+)",
        r"Industry[:\s]+([^\n\r]+)",
    ]) or ""

    posted = job.get("posted", "") or detail.get("posted", "") or ""

    return {
        "source": "linkedin",
        "title": detail.get("title") or job.get("title", ""),
        "company": detail.get("company") or job.get("company", ""),
        "location": detail.get("location") or job.get("location", ""),
        "working_pattern": working_pattern,
        "contract_type": contract_type,
        "ir35": ir35,
        "rate": rate,
        "sector": sector,
        "posted": posted,
        "url": job.get("url", ""),
        "skills": skills,
        "body": description,
    }