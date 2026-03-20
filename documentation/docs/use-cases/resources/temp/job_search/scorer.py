"""Score jobs based on Stephen's criteria."""

import re
from typing import Any

# Core technologies Stephen works with
CORE_TECHS = {
    ".net": [".net core", ".net 6", ".net 7", ".net 8", "asp.net core", "c#"],
    "azure": ["azure", "azure functions", "service bus", "cosmos db", "iot hub", "apim", "azure devops"],
    "ai_ml": ["ai", "machine learning", "langchain", "rag", "openai", "azure openai", "vector db", "llm"],
    "microservices": ["microservices", "event-driven", "event driven"],
    "python": ["python"],
    "blazor": ["blazor"],
    "react": ["react"],
    "angular": ["angular"],
    "docker": ["docker", "container", "kubernetes", "k8s"],
    "devops": ["devops", "cicd", "ci/cd", "azure devops", "github", "pipeline"],
}

SENIORITY_KEYWORDS_SENIOR = [
    "senior", "lead", "architect", "principal", "staff", "director", "head of"
]

SENIORITY_KEYWORDS_MID = [
    "mid-level", "mid level", "intermediate"
]

SENIORITY_KEYWORDS_JUNIOR = [
    "junior", "graduate", "entry", "intern", "trainee"
]

PREFERRED_SECTORS = {
    "healthcare": ["healthcare", "health", "medical", "medtech", "biotech", "pharma", "fhir", "hl7", "medical device"],
    "finance": ["finance", "fintech", "banking", "investment"],
    "legal": ["legal", "law", "legal tech"],
    "industrial": ["industrial", "manufacturing", "factory"],
    "energy": ["energy", "oil", "gas", "utilities"],
    "saas": ["saas", "cloud", "software"],
    "regtech": ["regtech", "compliance", "regulatory"],
}

SPECIAL_INTERESTS = [
    "ai", "ml", "machine learning", "healthcare", "gdpr", "fhir", "hl7",
    "medical device", "regulatory", "clean architecture", "ddd"
]

NEGATIVE_KEYWORDS = [
    "junior", "graduate", "intern", "entry level", "vb6", "classic asp", "permanent"
]

PREFERRED_RATE_FLOOR = 500  # £/day
PREFERRED_RATE_CEILING = 700


def extract_text(job: dict) -> str:
    """Extract searchable text from a job record."""
    text_parts = []

    if job["source"] == "jobserve":
        text_parts.append(job.get("subject", "").lower())
        text_parts.append(job.get("body", "").lower())
    else:  # linkedin
        text_parts.append(job.get("title", "").lower())
        text_parts.append(job.get("company", "").lower())
        text_parts.append(job.get("location", "").lower())
        text_parts.append(job.get("full_description", job.get("description", "")).lower())

    return " ".join(text_parts)


def score_tech_match(text: str) -> int:
    """Score technology match (0-3)."""
    matches = 0
    for _, keywords in CORE_TECHS.items():
        if any(kw in text for kw in keywords):
            matches += 1
    return min(matches, 3)


def score_seniority(text: str) -> int:
    """Score seniority level (0-2)."""
    for kw in SENIORITY_KEYWORDS_JUNIOR:
        if kw in text:
            return 0  # Auto-fail juniors
    for kw in SENIORITY_KEYWORDS_SENIOR:
        if kw in text:
            return 2
    if any(kw in text for kw in SENIORITY_KEYWORDS_MID):
        return 1
    return 1  # Default to mid-level if unclear


def score_rate(job: dict) -> int:
    """Score salary/rate match (0-2)."""
    rate = extract_rate(job)
    if rate is None:
        return 0  # No rate specified
    if rate >= PREFERRED_RATE_CEILING:
        return 2
    if rate >= PREFERRED_RATE_FLOOR:
        return 2
    if rate >= 400:
        return 1
    return 0


def extract_rate(job: dict) -> int | None:
    """Extract day rate from job (in £/day)."""
    if job["source"] == "jobserve":
        text = job.get("body", "")
        # Look for patterns like "£500" or "500 per day"
        matches = re.findall(r"£?(\d+)\s*(?:per day|/day|p\.d|pd)", text, re.IGNORECASE)
        if matches:
            return int(matches[0])
        matches = re.findall(r"£(\d+)", text)
        if matches:
            return int(matches[-1])  # Last mention likely closest to actual rate
    else:  # linkedin
        salary = job.get("salary", "")
        if salary:
            matches = re.findall(r"(\d+)", salary)
            if matches:
                val = int(matches[0])
                if "k" in salary.lower():
                    val *= 1000
                if "per year" in salary.lower():
                    return int(val / 250)  # Convert annual to daily (250 work days)
                return val
    return None


def score_sector(text: str) -> int:
    """Score sector match (0-2)."""
    matches = 0
    for sector, keywords in PREFERRED_SECTORS.items():
        if any(kw in text for kw in keywords):
            matches += 1
    if matches >= 2:
        return 2
    if matches == 1:
        return 1
    return 0


def score_location(job: dict) -> int:
    """Score location match (0-2)."""
    text = ""
    if job["source"] == "jobserve":
        text = job.get("body", "").lower()
    else:
        text = job.get("location", "").lower()

    # Preferred: Remote UK or London
    if "remote" in text and ("uk" in text or "united kingdom" in text):
        return 2
    if "london" in text:
        return 2
    if "remote" in text:
        return 1  # Remote but maybe not UK
    if "london" in text or "uk" in text:
        return 1
    return 0


def score_ir35(job: dict) -> int:
    """Bonus point for outside IR35 (0 or 1)."""
    text = ""
    if job["source"] == "jobserve":
        text = job.get("body", "").lower()
    else:
        text = job.get("description", "").lower()

    if "outside ir35" in text:
        return 1
    if "inside ir35" in text:
        return 0
    return 0  # Not specified, no bonus/penalty


def score_special_interests(text: str) -> int:
    """Bonus point for special interests (0 or 1)."""
    for interest in SPECIAL_INTERESTS:
        if interest in text:
            return 1
    return 0


def should_exclude(job: dict) -> bool:
    """Check if job should be excluded."""
    text = extract_text(job)
    for kw in NEGATIVE_KEYWORDS:
        if kw in text:
            return True
    return False


def score_job(job: dict) -> int:
    """Score a job 0-10."""
    if should_exclude(job):
        return 0

    text = extract_text(job)

    tech = score_tech_match(text)
    seniority = score_seniority(text)
    rate = score_rate(job)
    sector = score_sector(text)
    location = score_location(job)
    ir35 = score_ir35(job)
    special = score_special_interests(text)

    total = tech + seniority + rate + sector + location + ir35 + special
    return min(max(total, 0), 10)


def get_score_breakdown(job: dict) -> dict:
    """Return detailed score breakdown."""
    text = extract_text(job)

    return {
        "tech": score_tech_match(text),
        "seniority": score_seniority(text),
        "rate": score_rate(job),
        "sector": score_sector(text),
        "location": score_location(job),
        "ir35": score_ir35(job),
        "special": score_special_interests(text),
    }


def get_rate_display(job: dict) -> str:
    """Format rate for display."""
    rate = extract_rate(job)
    if rate:
        return f"£{rate}/day"
    if job["source"] == "jobserve":
        salary = re.search(r"([^a-z0-9](?:.*?)salary[^a-z0-9].*?[£$€]\d+[^a-z0-9])", job.get("body", ""), re.IGNORECASE)
        if salary:
            return salary.group(1).strip()
    return job.get("salary", "Not specified")
