import re
from datetime import datetime
from collections import Counter


def build_report(jobserve_jobs: list[dict], linkedin_jobs: list[dict], today: datetime) -> list[str]:
    date_str = today.strftime("%d %B %Y")
    date_iso = today.strftime("%Y-%m-%d")

    all_jobs = jobserve_jobs + linkedin_jobs
    top10 = sorted(all_jobs, key=lambda x: x["score"], reverse=True)[:10]

    sections = []
    sections.append(_title_section(date_str, date_iso))
    sections.append(_top10_section(top10))
    sections.append(_jobserve_section(jobserve_jobs))
    sections.append(_linkedin_section(linkedin_jobs))
    sections.append(_stats_section(jobserve_jobs, linkedin_jobs, today))
    return sections


def _title_section(date_str: str, date_iso: str) -> str:
    return f"# Today's Job Opportunities - {date_str}\n\nGenerated: {date_iso}\n\n"


def _anchor(job: dict) -> str:
    raw = job.get("title", "untitled") + "-" + job.get("company", job.get("agency", ""))
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:60]


def _rate_display(job: dict) -> str:
    rate = job.get("rate_str", "") or job.get("rate", "")
    return rate if rate else "Rate TBC"


def _location_display(job: dict) -> str:
    loc = job.get("location", "") or job.get("working_pattern", "")
    return loc if loc else "Location TBC"


def _top10_section(jobs: list[dict]) -> str:
    lines = ["## Top 10 Opportunities\n\n"]
    for i, job in enumerate(jobs, 1):
        anc = _anchor(job)
        title = job.get("title", "Untitled")
        company = job.get("company", job.get("agency", ""))
        score = job.get("score", 0)
        rate = _rate_display(job)
        loc = _location_display(job)
        duration = job.get("duration", "")
        ir35 = job.get("ir35", "")
        skills_preview = ", ".join(job.get("skills", [])[:4])

        summary_parts = [x for x in [rate, loc, duration, ir35, skills_preview] if x]
        summary = " | ".join(summary_parts)

        display = f"{title}"
        if company:
            display += f" — {company}"

        lines.append(f"{i}. [**{display}**](#{anc}) — Score: **{score}/10**  \n   {summary}\n\n")

    return "".join(lines)


def _jobserve_section(jobs: list[dict]) -> str:
    if not jobs:
        return "## JobServe Roles\n\n*No JobServe roles found scoring 5 or above this week.*\n\n"

    lines = ["## JobServe Roles\n\n"]
    for job in jobs:
        anc = _anchor(job)
        title = job.get("title", "Untitled")
        score = job.get("score", 0)
        location = _location_display(job)
        rate = _rate_display(job)
        duration = job.get("duration", "Not specified")
        ir35 = job.get("ir35", "Not specified")
        agency = job.get("agency", "Not specified")
        ref = job.get("ref", "")
        agency_ref = f"{agency}" + (f" | Ref: {ref}" if ref else "")
        job_url = job.get("job_url", "")
        apply_url = job.get("apply_url", "")
        skills = ", ".join(job.get("skills", [])[:8])
        body_preview = _body_preview(job.get("body", ""), 600)
        rationale = _jobserve_rationale(job)

        lines.append(f'<a id="{anc}"></a>\n\n')
        lines.append(f"### {title}\n\n")
        lines.append(f"**Score:** {score}/10  \n")
        lines.append(f"**Location:** {location}  \n")
        lines.append(f"**Rate:** {rate}  \n")
        lines.append(f"**Duration:** {duration}  \n")
        lines.append(f"**IR35:** {ir35}  \n")
        lines.append(f"**Agency/Ref:** {agency_ref}  \n")
        if skills:
            lines.append(f"**Key Skills:** {skills}  \n")
        lines.append(f"\n{body_preview}\n\n")

        link_parts = []
        if job_url:
            link_parts.append(f"[Job Spec]({job_url})")
        if apply_url and apply_url != job_url:
            link_parts.append(f"[Apply]({apply_url})")
        if link_parts:
            lines.append(f"**Links:** {' | '.join(link_parts)}\n\n")

        lines.append(f"**Score Rationale:** {rationale}\n\n")
        lines.append("---\n\n")

    return "".join(lines)


def _linkedin_section(jobs: list[dict]) -> str:
    if not jobs:
        return "## LinkedIn Roles\n\n*No LinkedIn roles found scoring 5 or above this week.*\n\n"

    lines = ["## LinkedIn Roles\n\n"]
    for job in jobs:
        anc = _anchor(job)
        company = job.get("company", "Unknown Company")
        title = job.get("title", "Untitled")
        display_title = f"{company} — {title}"
        score = job.get("score", 0)
        location = _location_display(job)
        contract_type = job.get("contract_type", "Not specified")
        working_pattern = job.get("working_pattern", "Not specified")
        sector = job.get("sector", "Not specified")
        posted = job.get("posted", "Not specified")
        url = job.get("url", "")
        ir35 = job.get("ir35", "")
        body_preview = _body_preview(job.get("body", ""), 600)
        rationale = _linkedin_rationale(job)

        lines.append(f'<a id="{anc}"></a>\n\n')
        lines.append(f"### {display_title}\n\n")
        lines.append(f"**Score:** {score}/10  \n")
        lines.append(f"**Company:** {company}  \n")
        lines.append(f"**Location:** {location}  \n")
        lines.append(f"**Type/Pattern:** {contract_type} / {working_pattern}  \n")
        lines.append(f"**Sector:** {sector}  \n")
        lines.append(f"**Posted:** {posted}  \n")
        if ir35:
            lines.append(f"**IR35:** {ir35}  \n")
        lines.append(f"\n{body_preview}\n\n")

        if url:
            lines.append(f"**Link:** [{title}]({url})\n\n")

        lines.append(f"**Score Rationale:** {rationale}\n\n")
        lines.append("---\n\n")

    return "".join(lines)


def _body_preview(body: str, max_chars: int) -> str:
    body = body.strip()
    if len(body) <= max_chars:
        return body
    truncated = body[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[:last_nl]
    return truncated + "..."


def _jobserve_rationale(job: dict) -> str:
    parts = []
    score = job.get("score", 0)
    skills = job.get("skills", [])
    ai_skills = [s for s in skills if s.lower() in {
        "llm", "agent", "openai", "anthropic", "claude", "gpt", "rag",
        "langchain", "vector", "embedding", "mcp", "pytorch", "tensorflow",
        "whisper", "azure openai", "semantic kernel", "function calling", "tool use", "prompt"
    }]
    ir35 = job.get("ir35", "")
    rate = job.get("rate_str", "") or job.get("rate", "")
    location = job.get("location", "")

    parts.append(f"Score {score}/10.")
    if ai_skills:
        parts.append(f"AI/LLM skills matched: {', '.join(ai_skills[:5])}.")
    if "outside" in ir35.lower():
        parts.append("Outside IR35 — strong contract positive.")
    elif "inside" in ir35.lower():
        parts.append("Inside IR35 — reduces net take-home.")
    if rate:
        parts.append(f"Rate: {rate}.")
    if location:
        parts.append(f"Location: {location}.")
    if not ai_skills:
        parts.append("No primary AI/LLM match — scored on engineering foundation skills.")
    return " ".join(parts)


def _linkedin_rationale(job: dict) -> str:
    parts = []
    score = job.get("score", 0)
    skills = job.get("skills", [])
    ai_skills = [s for s in skills if s.lower() in {
        "llm", "agent", "openai", "anthropic", "claude", "gpt", "rag",
        "langchain", "vector", "embedding", "mcp", "pytorch", "tensorflow",
        "whisper", "azure openai", "semantic kernel", "function calling", "tool use", "prompt"
    }]
    contract_type = job.get("contract_type", "")
    ir35 = job.get("ir35", "")
    company = job.get("company", "")
    sector = job.get("sector", "")

    parts.append(f"Score {score}/10.")
    if ai_skills:
        parts.append(f"AI/LLM skills matched: {', '.join(ai_skills[:5])}.")
    if re.search(r"permanent", contract_type, re.IGNORECASE):
        parts.append("**Permanent role** — outside candidate's stated contract preference.")
    if "outside" in ir35.lower():
        parts.append("Outside IR35 — contract positive.")
    elif "inside" in ir35.lower():
        parts.append("Inside IR35 noted.")
    if company:
        parts.append(f"Company: {company}.")
    if sector and sector != "Not specified":
        parts.append(f"Sector: {sector}.")
    if not ai_skills:
        parts.append("Scored on .NET/Azure/engineering foundation — limited AI signal in posting.")
    return " ".join(parts)


def _stats_section(jobserve_jobs: list[dict], linkedin_jobs: list[dict], today: datetime) -> str:
    all_jobs = jobserve_jobs + linkedin_jobs
    total = len(all_jobs)
    total_js = len(jobserve_jobs)
    total_li = len(linkedin_jobs)

    scoring_5_plus = [j for j in all_jobs if j["score"] >= 5]
    avg_score = round(sum(j["score"] for j in all_jobs) / total, 1) if total else 0

    skill_counter: Counter = Counter()
    for job in all_jobs:
        for skill in job.get("skills", []):
            skill_counter[skill.lower()] += 1
    top_skills = [s for s, _ in skill_counter.most_common(8)]

    sector_counter: Counter = Counter()
    for job in all_jobs:
        sec = job.get("sector", "")
        if sec and sec != "Not specified":
            sector_counter[sec] += 1

    contract_count = 0
    permanent_count = 0
    for job in all_jobs:
        ct = job.get("contract_type", "") + job.get("body", "")
        if re.search(r"\bpermanent\b|\bperm\b", ct, re.IGNORECASE):
            permanent_count += 1
        elif re.search(r"\bcontract\b|\bfreelance\b|\binterim\b", ct, re.IGNORECASE):
            contract_count += 1

    location_counter: Counter = Counter()
    for job in all_jobs:
        loc = (job.get("location", "") or job.get("working_pattern", "")).lower()
        if "remote" in loc:
            location_counter["Remote"] += 1
        elif "london" in loc:
            location_counter["London"] += 1
        elif "hybrid" in loc:
            location_counter["Hybrid"] += 1
        else:
            location_counter["Other/TBC"] += 1

    outside_count = sum(1 for j in all_jobs if re.search(r"outside ir35", j.get("ir35", "") + j.get("body", ""), re.IGNORECASE))
    inside_count = sum(1 for j in all_jobs if re.search(r"inside ir35", j.get("ir35", "") + j.get("body", ""), re.IGNORECASE))
    ir35_unknown = total - outside_count - inside_count

    date_str = today.strftime("%d %B %Y")
    date_iso = today.strftime("%Y-%m-%d")

    lines = ["## Summary Statistics\n\n"]
    lines.append(f"**Report Date:** {date_str}  \n")
    lines.append(f"**Total Jobs Reviewed:** {total} (JobServe: {total_js} | LinkedIn: {total_li})  \n")
    lines.append(f"**Jobs Scoring 5+:** {len(scoring_5_plus)}  \n")
    lines.append(f"**Average Score:** {avg_score}/10  \n\n")

    lines.append("### Top Technologies Mentioned\n\n")
    lines.append(", ".join(top_skills) if top_skills else "N/A")
    lines.append("\n\n")

    lines.append("### Sectors\n\n")
    if sector_counter:
        for sec, cnt in sector_counter.most_common(8):
            lines.append(f"- {sec}: {cnt}\n")
    else:
        lines.append("- Sector data not parsed from postings\n")
    lines.append("\n")

    lines.append("### Contract vs Permanent\n\n")
    lines.append(f"- Contract/Freelance: {contract_count}  \n")
    lines.append(f"- Permanent: {permanent_count}  \n")
    lines.append(f"- Unknown/Mixed: {total - contract_count - permanent_count}  \n\n")

    lines.append("### Location Distribution\n\n")
    for loc, cnt in location_counter.most_common():
        lines.append(f"- {loc}: {cnt}  \n")
    lines.append("\n")

    lines.append("### IR35 Breakdown\n\n")
    lines.append(f"- Outside IR35: {outside_count}  \n")
    lines.append(f"- Inside IR35: {inside_count}  \n")
    lines.append(f"- Not Specified: {ir35_unknown}  \n\n")

    lines.append("### Market Observations\n\n")
    observations = _market_observations(all_jobs, outside_count, total, contract_count, permanent_count)
    for obs in observations:
        lines.append(f"- {obs}\n")
    lines.append("\n")

    lines.append("### Recommendations\n\n")
    recommendations = _recommendations(all_jobs, jobserve_jobs, linkedin_jobs)
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. {rec}\n")
    lines.append("\n")

    lines.append(f"### Search Criteria\n\n")
    lines.append(f"- **Date:** {date_iso}  \n")
    lines.append(f"- **Gmail Query:** JobServe emails past 7 days  \n")
    lines.append(f"- **LinkedIn Keywords:** AI Agent Engineer, LLM Engineer, AI Architect Python, .NET AI Engineer, Azure AI Engineer  \n")
    lines.append(f"- **Location:** United Kingdom  \n")
    lines.append(f"- **Experience Level:** Senior  \n")
    lines.append(f"- **Minimum Score Threshold:** 5/10  \n")

    return "".join(lines)


def _market_observations(jobs: list[dict], outside_count: int, total: int, contract_count: int, permanent_count: int) -> list[str]:
    obs = []
    if total == 0:
        return ["No jobs retrieved this week — check Gmail/LinkedIn connectivity."]

    ai_jobs = [j for j in jobs if any(
        re.search(p, j.get("title", "") + j.get("body", ""), re.IGNORECASE)
        for p in [r"\bllm\b", r"\bagent\b", r"\bai\b", r"\bml\b"]
    )]
    pct_ai = round(len(ai_jobs) / total * 100) if total else 0
    obs.append(f"{pct_ai}% of roles this week have an AI/ML component, reflecting strong market demand for AI-skilled engineers.")

    if outside_count > 0:
        pct_outside = round(outside_count / total * 100)
        obs.append(f"{pct_outside}% of roles are explicitly Outside IR35 — contractor market remains active for senior AI talent.")
    else:
        obs.append("IR35 status not prominently advertised — worth clarifying at agency stage for all contract roles.")

    if permanent_count > contract_count:
        obs.append("Permanent roles outnumber contracts this week — consider whether some perm opportunities with AI mandates warrant exploration.")
    elif contract_count > 0:
        obs.append("Contract roles dominate this week's results, aligning well with the candidate's availability preference.")

    high_score = [j for j in jobs if j["score"] >= 8]
    obs.append(f"{len(high_score)} roles scored 8+ indicating strong profile alignment — prioritise these for immediate outreach.")

    remote_jobs = [j for j in jobs if re.search(r"\bremote\b", j.get("location", "") + j.get("working_pattern", ""), re.IGNORECASE)]
    obs.append(f"{len(remote_jobs)} roles are fully remote or remote-first, supporting flexible working preferences.")

    azure_ai_jobs = [j for j in jobs if re.search(r"azure.*ai|azure.*openai|azure.*ml", j.get("body", ""), re.IGNORECASE)]
    obs.append(f"Azure AI/OpenAI is mentioned in {len(azure_ai_jobs)} roles, confirming strong demand for the candidate's Azure + AI crossover skills.")

    return obs


def _recommendations(all_jobs: list[dict], jobserve_jobs: list[dict], linkedin_jobs: list[dict]) -> list[str]:
    top = sorted(all_jobs, key=lambda x: x["score"], reverse=True)

    recs = []
    if top:
        t = top[0]
        recs.append(f"Prioritise **{t.get('title', 'top role')}** ({t.get('company', t.get('agency', 'via agency'))}) — highest score {t.get('score')}/10. Apply or respond today.")

    outside = [j for j in all_jobs if re.search(r"outside ir35", j.get("ir35", "") + j.get("body", ""), re.IGNORECASE)]
    if outside:
        o = outside[0]
        recs.append(f"Fast-track Outside IR35 roles — {o.get('title', 'role')} leads; verify engagement model before committing time to interviews.")

    recs.append("For LinkedIn roles without rate info, research company funding stage and typical senior contract rates before engaging — avoid time-wasters.")
    recs.append("Tailor cover notes to emphasise production agent systems, agentic loop architecture, and MCP server experience — these are rare and highly valued signals.")

    ai_focused = [j for j in all_jobs if j["score"] >= 8]
    if len(ai_focused) >= 2:
        recs.append(f"With {len(ai_focused)} roles scoring 8+, batch your applications and maintain a tracker to avoid pipeline confusion across concurrent opportunities.")

    recs.append("For any Healthcare AI roles, explicitly reference HL7/FHIR/DICOM experience and GDPR compliance — this crossover is a strong differentiator in a niche market.")
    return recs