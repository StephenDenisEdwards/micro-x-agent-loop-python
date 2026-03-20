"""Generate markdown report from scored jobs."""

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Any

from .scorer import (
    extract_rate,
    extract_text,
    get_rate_display,
    get_score_breakdown,
)


def generate_anchor(title: str) -> str:
    """Generate a URL-safe anchor ID."""
    safe = re.sub(r"[^\w\s-]", "", title.lower())
    safe = re.sub(r"[-\s]+", "-", safe)
    return safe[:50]


def get_job_title(job: dict) -> str:
    """Extract job title."""
    if job["source"] == "jobserve":
        subject = job.get("subject", "")
        match = re.match(r"[^:]+:\s*(.+)", subject)
        if match:
            return match.group(1).strip()
        return subject
    else:
        return job.get("full_title", job.get("title", "Unknown"))


def get_job_location(job: dict) -> str:
    """Extract location."""
    if job["source"] == "jobserve":
        body = job.get("body", "")
        match = re.search(r"(?:Location|Based)[\s:]+([^\n]+)", body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "Not specified"
    else:
        return job.get("full_location", job.get("location", "Not specified"))


def get_job_duration(job: dict) -> str:
    """Extract contract duration."""
    if job["source"] == "jobserve":
        body = job.get("body", "")
        match = re.search(r"(?:Duration|Length)[\s:]+([^\n]+)", body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "Not specified"
    else:
        return "Not specified"


def get_job_url(job: dict) -> str:
    """Extract job URL."""
    if job["source"] == "jobserve":
        raw = job.get("raw_email", {})
        body = raw.get("body", "")
        match = re.search(r"(https?://\S+)", body)
        if match:
            return match.group(1).strip()
        return ""
    else:
        return job.get("url", "")


def get_job_summary(job: dict) -> str:
    """Generate one-line summary for top 10."""
    rate = get_rate_display(job)
    location = get_job_location(job)
    duration = get_job_duration(job)

    text = extract_text(job)
    techs = []
    if ".net" in text:
        techs.append(".NET")
    if "azure" in text:
        techs.append("Azure")
    if "ai" in text or "machine learning" in text:
        techs.append("AI/ML")
    if "microservices" in text:
        techs.append("Microservices")

    summary = f"{duration} at {rate}, {location}."
    if techs:
        summary += f" Tech: {', '.join(techs)}."
    return summary


def get_why_score(job: dict, score: int) -> str:
    """Generate explanation for score."""
    breakdown = get_score_breakdown(job)
    text = extract_text(job)

    parts = []

    tech_matched = breakdown["tech"]
    if tech_matched > 0:
        parts.append(f"Matches {tech_matched} core tech")

    rate = extract_rate(job)
    if rate:
        if rate >= 600:
            parts.append(f"Strong rate (£{rate}/day)")
        elif rate >= 500:
            parts.append(f"Good rate (£{rate}/day)")
        else:
            parts.append(f"Lower rate (£{rate}/day)")

    location_score = breakdown["location"]
    if location_score == 2:
        parts.append("Preferred location")
    elif location_score == 1:
        parts.append("Acceptable location")

    sector_score = breakdown["sector"]
    if sector_score > 0:
        parts.append("Aligned sector")

    seniority_score = breakdown["seniority"]
    if seniority_score == 2:
        parts.append("Senior level")
    elif seniority_score == 1:
        parts.append("Mid-level")

    if breakdown["ir35"] == 1:
        parts.append("Outside IR35")

    if breakdown["special"] == 1:
        parts.append("Special interest (AI/Healthcare/etc)")

    summary = ". ".join(parts) + "."
    return summary


def group_jobs_by_category(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split jobs into JobServe and LinkedIn."""
    jobserve = [j for j in jobs if j["source"] == "jobserve"]
    linkedin = [j for j in jobs if j["source"] == "linkedin"]
    return jobserve, linkedin


def get_all_techs(jobs: list[dict]) -> list[tuple[str, int]]:
    """Count technology mentions."""
    tech_names = [
        "C#", ".NET Core", "Azure", "AI/ML", "Microservices",
        "Python", "Blazor", "React", "Angular", "Docker", "DevOps"
    ]
    tech_keywords = [
        (".net", "C#/.NET"),
        ("azure", "Azure"),
        ("ai", "AI/ML"),
        ("machine learning", "AI/ML"),
        ("microservices", "Microservices"),
        ("python", "Python"),
        ("blazor", "Blazor"),
        ("react", "React"),
        ("angular", "Angular"),
        ("docker", "Docker"),
        ("devops", "DevOps"),
    ]

    counter = Counter()
    for job in jobs:
        text = extract_text(job)
        for kw, label in tech_keywords:
            if kw in text:
                counter[label] += 1

    return counter.most_common(8)


def get_all_sectors(jobs: list[dict]) -> list[tuple[str, int]]:
    """Count sector mentions."""
    sector_keywords = [
        ("healthcare", "Healthcare"),
        ("finance", "Finance"),
        ("legal", "Legal"),
        ("industrial", "Industrial"),
        ("energy", "Energy"),
        ("saas", "SaaS"),
        ("regtech", "RegTech"),
    ]

    counter = Counter()
    for job in jobs:
        text = extract_text(job)
        for kw, label in sector_keywords:
            if kw in text:
                counter[label] += 1

    return counter.most_common(20)


def get_all_locations(jobs: list[dict]) -> list[tuple[str, int]]:
    """Count location mentions."""
    locations = Counter()
    for job in jobs:
        loc = get_job_location(job)
        locations[loc] += 1
    return locations.most_common(20)


def get_ir35_stats(jobs: list[dict]) -> dict:
    """Count IR35 status."""
    inside = 0
    outside = 0
    not_spec = 0

    for job in jobs:
        text = extract_text(job)
        if "outside ir35" in text:
            outside += 1
        elif "inside ir35" in text:
            inside += 1
        else:
            not_spec += 1

    return {"inside": inside, "outside": outside, "not_specified": not_spec}


def get_contract_types(jobs: list[dict]) -> dict:
    """Count contract vs permanent."""
    contract = 0
    permanent = 0
    not_spec = 0

    for job in jobs:
        text = extract_text(job)
        if "contract" in text:
            contract += 1
        elif "permanent" in text:
            permanent += 1
        else:
            not_spec += 1

    return {"contract": contract, "permanent": permanent, "not_specified": not_spec}


def make_top_10_section(scored_jobs: list[dict]) -> str:
    """Generate top 10 section."""
    lines = ["## Top 10 Best Matches\n"]

    for i, (job, score) in enumerate(scored_jobs[:10], 1):
        title = get_job_title(job)
        anchor = generate_anchor(title)
        summary = get_job_summary(job)

        lines.append(f"{i}. **[{title}](#{anchor})** - Score: {score}/10")
        lines.append(f"   {summary}\n")

    lines.append("---\n")
    return "\n".join(lines)


def make_jobserve_section(jobs: list[dict]) -> str:
    """Generate JobServe section."""
    lines = ["## JobServe Jobs (24 Hours)\n"]

    for job, score in jobs:
        title = get_job_title(job)
        anchor = generate_anchor(title)

        lines.append(f'<a id="{anchor}"></a>\n')
        lines.append(f"### {title}")
        lines.append(f"**Score: {score}/10**\n")

        location = get_job_location(job)
        rate = get_rate_display(job)
        duration = get_job_duration(job)

        lines.append(f"**Location:** {location}")
        lines.append(f"**Rate:** {rate}")
        lines.append(f"**Duration:** {duration}\n")

        ir35 = "Outside IR35" if "outside ir35" in extract_text(job) else "Not specified"
        lines.append(f"**IR35:** {ir35}")

        subject = job.get("subject", "")
        match = re.search(r"\[(\w+)\]", subject)
        ref = match.group(1) if match else "N/A"
        agency = re.search(r"from:([^\s@]+)", job.get("from", ""))
        agency_name = agency.group(1) if agency else "JobServe"
        lines.append(f"**Posted:** {agency_name}, Ref: {ref}\n")

        body = job.get("body", "")
        summary_match = re.search(r"(?:Summary|Overview|Description)[\s\n]+([\s\S]+?)(?=\n\n|Location|Based)", body, re.IGNORECASE)
        if summary_match:
            summary_text = summary_match.group(1).strip()[:400]
        else:
            summary_text = body[:400]

        lines.append(f"**Summary:**")
        lines.append(f"{summary_text}\n")

        url = get_job_url(job)
        lines.append("**Links:**")
        if url:
            lines.append(f"- [View Job]({url})\n")
        else:
            lines.append("- Email specification provided\n")

        why = get_why_score(job, score)
        lines.append("**Why this score:**")
        lines.append(f"{why}\n")
        lines.append("---\n")

    return "\n".join(lines)


def make_linkedin_section(jobs: list[dict]) -> str:
    """Generate LinkedIn section."""
    lines = ["## LinkedIn Jobs (24 Hours)\n"]

    for job, score in jobs:
        title = get_job_title(job)
        company = job.get("full_company", job.get("company", "Unknown"))
        anchor = generate_anchor(f"{company}-{title}")

        lines.append(f'<a id="{anchor}"></a>\n')
        lines.append(f"### {company} - {title}")
        lines.append(f"**Score: {score}/10**\n")

        location = get_job_location(job)
        posted = job.get("posted", "Unknown")
        sector = "Not specified"

        lines.append(f"**Company:** {company}")
        lines.append(f"**Location:** {location}")
        lines.append(f"**Type:** Contract")
        lines.append(f"**Sector:** {sector}")
        lines.append(f"**Posted:** {posted}\n")

        description = job.get("full_description", job.get("description", ""))[:400]
        lines.append("**Summary:**")
        lines.append(f"{description}\n")

        url = job.get("url", "")
        if url:
            lines.append(f"**Link:** [View Job]({url})\n")

        why = get_why_score(job, score)
        lines.append("**Why this score:**")
        lines.append(f"{why}\n")
        lines.append("---\n")

    return "\n".join(lines)


def make_summary_section(all_jobs: list[dict], scored_jobs: list[dict]) -> str:
    """Generate summary statistics section."""
    lines = ["## Summary Statistics\n"]

    jobserve, linkedin = group_jobs_by_category(all_jobs)
    above_5 = [j for j in scored_jobs if j[1] >= 5]

    lines.append(f"**Total Jobs Found:** {len(all_jobs)} "
                 f"({len(jobserve)} JobServe + {len(linkedin)} LinkedIn)")
    lines.append(f"**Jobs Scoring 5+/10:** {len(above_5)}")

    if above_5:
        avg = sum(s for _, s in above_5) / len(above_5)
        lines.append(f"**Average Score (5+ only):** {avg:.1f}/10\n")
    else:
        lines.append("**Average Score (5+ only):** N/A\n")

    lines.append("**Top Technologies:**")
    for tech, count in get_all_techs(all_jobs):
        lines.append(f"- {tech}: {count} roles")
    lines.append("")

    lines.append("**Sectors:**")
    for sector, count in get_all_sectors(all_jobs):
        lines.append(f"- {sector}: {count}")
    lines.append("")

    lines.append("**Contract vs Permanent:**")
    contract_stats = get_contract_types(all_jobs)
    lines.append(f"- Contract roles: {contract_stats['contract']}")
    lines.append(f"- Permanent roles: {contract_stats['permanent']}")
    lines.append(f"- Not specified: {contract_stats['not_specified']}\n")

    lines.append("**Location Distribution:**")
    for loc, count in get_all_locations(all_jobs):
        lines.append(f"- {loc}: {count}")
    lines.append("")

    lines.append("**IR35 Status:**")
    ir35_stats = get_ir35_stats(all_jobs)
    lines.append(f"- Outside IR35: {ir35_stats['outside']} contracts")
    lines.append(f"- Inside IR35: {ir35_stats['inside']} contracts")
    lines.append(f"- Not specified: {ir35_stats['not_specified']}\n")

    lines.append("**Key Observations:**")
    observations = [
        f"Market has {len(all_jobs)} roles available (JobServe + LinkedIn recent).",
        f"{len(above_5)} roles score 5+/10 — worth pursuing.",
        f"Most common tech: {get_all_techs(all_jobs)[0][0] if get_all_techs(all_jobs) else 'N/A'}.",
        f"Top sector: {get_all_sectors(all_jobs)[0][0] if get_all_sectors(all_jobs) else 'N/A'}.",
        f"{ir35_stats['outside']} roles confirmed outside IR35.",
    ]
    for i, obs in enumerate(observations[:5], 1):
        lines.append(f"{i}. {obs}")
    lines.append("")

    lines.append("**Recommended Actions:**")
    top_jobs = scored_jobs[:5]
    for i, (job, score) in enumerate(top_jobs, 1):
        title = get_job_title(job)
        lines.append(f"{i}. Apply to **{title}** (Score: {score}/10)")
    lines.append("")

    lines.append("---\n")
    today = datetime.now().strftime("%B %d, %Y")
    lines.append(f"*Report generated: {today}*")
    lines.append("*Search criteria: Stephen Edwards — Senior Architect, .NET/Azure/AI-ML, £500-700+/day, London/Remote UK*")

    return "\n".join(lines)
