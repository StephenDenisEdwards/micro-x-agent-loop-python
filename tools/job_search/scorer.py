import re

AI_BOOST_PATTERNS = [
    r"agentic\s*loop",
    r"multi.?model",
    r"tool\s*(use|calling|orchestration)",
    r"function\s*calling",
    r"mcp\s*(server|protocol)?",
    r"production\s*llm",
    r"llm\s*(integration|architect|engineer|system)",
    r"agent\s*(architect|framework|system|platform)",
    r"prompt\s*(engineer|cach|optim|compres)",
    r"cost.?(optim|engineer|aware)",
    r"token\s*(budget|econom|track)",
    r"context\s*(window|compact|manag)",
    r"anthropic|claude",
    r"openai\s*api|gpt.?4|gpt.?5",
    r"langchain|langgraph",
    r"rag\s+|retrieval.?augment",
    r"vector\s*(db|database|store|search)",
    r"embedding",
    r"semantic\s*kernel",
    r"azure\s*openai",
    r"healthcare.*ai|ai.*healthcare|medical.*ai",
]

EXCLUDE_PATTERNS = [
    r"\bjunior\b",
    r"\bgraduate\b",
    r"\bgrad\b",
    r"\bno.?code\b",
    r"\bnon.?technical\b",
    r"\bentry.?level\b",
    r"\bprompt.?only\b",
]

SENIORITY_PATTERNS = [
    r"\bsenior\b", r"\blead\b", r"\barchitect\b",
    r"\bstaff\b", r"\bprincipal\b", r"\bhead\s+of\b",
    r"\bcto\b", r"\bvp\b",
]

PREFERRED_SECTORS = [
    r"ai\s*(startup|company|firm|platform)",
    r"machine\s*learning",
    r"developer\s*tool",
    r"healthcare\s*ai|health\s*tech|medtech",
    r"fintech|financial\s*tech",
    r"saas",
    r"regtech",
    r"enterprise\s*ai",
]

PRIMARY_AI_SKILLS = [
    r"\bllm\b", r"\bagent\b", r"\bprompt\b", r"\brag\b",
    r"\blangchain\b", r"\bopenai\b", r"\banthropic\b", r"\bclaude\b",
    r"\bembedding\b", r"\bvector\b", r"\bmcp\b", r"\bhuggingface\b",
    r"\bpytorch\b|\btorch\b", r"\btensorflow\b",
    r"\bwhisper\b", r"\bspeech.to.text\b",
    r"\bazure\s*openai\b", r"\bsemantic\s*kernel\b",
    r"\bfunction\s*calling\b", r"\btool\s*use\b",
]

FOUNDATION_SKILLS = [
    r"\bpython\b", r"\bc#\b|\.net\b", r"\bazure\b",
    r"\btypescript\b|\bnode\.?js\b",
    r"\bhl7\b|\bfhir\b|\bdicom\b",
    r"\bmicroservices\b", r"\bdocker\b",
]


def _count_matches(text: str, patterns: list[str]) -> int:
    count = 0
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            count += 1
    return count


def _extract_daily_rate(text: str) -> float:
    # Match explicit daily rate — capture first number in a possible range
    daily_patterns = [
        r"£([\d,]+)\s*(?:[-–]\s*£[\d,]+\s*)?(?:per\s*day|/day|pd|p/d)\b",
        r"([\d,]+)\s*(?:[-–]\s*[\d,]+\s*)?(?:per\s*day|/day|pd|p/d)\b",
    ]
    for pat in daily_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass

    annual_patterns = [
        r"£([\d,]+)\s*(?:k|,000)?\s*(?:per\s*annum|pa|/year|/yr|annually)",
        r"£([\d,]+)k\b",
    ]
    for pat in annual_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                raw = m.group(1).replace(",", "")
                val = float(raw)
                if val < 1000:
                    val *= 1000
                return val / 220
            except ValueError:
                pass
    return 0.0


def _is_outside_ir35(text: str) -> bool:
    return bool(re.search(r"outside\s*ir35", text, re.IGNORECASE))


def _is_remote_or_london(text: str) -> bool:
    return bool(re.search(r"\bremote\b|\blondon\b|\buk\s*wide\b|\bnationwide\b", text, re.IGNORECASE))


def score_job(job: dict) -> int:
    text = " ".join([
        job.get("title", ""),
        job.get("body", ""),
        job.get("location", ""),
        job.get("sector", ""),
        job.get("rate_str", "") or job.get("rate", ""),
        job.get("working_pattern", ""),
        job.get("contract_type", ""),
        " ".join(job.get("skills", [])),
    ])

    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            title_text = job.get("title", "").lower()
            if re.search(pat, title_text, re.IGNORECASE):
                return 0

    boost_count = _count_matches(text, AI_BOOST_PATTERNS)
    ai_skill_count = _count_matches(text, PRIMARY_AI_SKILLS)
    foundation_count = _count_matches(text, FOUNDATION_SKILLS)
    seniority_match = _count_matches(text, SENIORITY_PATTERNS) > 0
    sector_match = _count_matches(text, PREFERRED_SECTORS) > 0
    outside_ir35 = _is_outside_ir35(text)
    location_ok = _is_remote_or_london(text)

    rate = _extract_daily_rate(text)
    rate_score = 0
    if rate >= 800:
        rate_score = 3
    elif rate >= 650:
        rate_score = 2
    elif rate >= 550:
        rate_score = 1
    elif rate == 0:
        rate_score = 1

    base = 0

    if ai_skill_count >= 5 and boost_count >= 3:
        base = 9
    elif ai_skill_count >= 3 and boost_count >= 2:
        base = 8
    elif ai_skill_count >= 2 and boost_count >= 1:
        base = 7
    elif ai_skill_count >= 1:
        base = 6
    elif foundation_count >= 3:
        base = 5
    elif foundation_count >= 1:
        base = 4
    else:
        base = 3

    bonus = 0
    if seniority_match:
        bonus += 1
    if sector_match:
        bonus += 1
    if outside_ir35:
        bonus += 1
    if rate_score >= 2:
        bonus += 1
    if boost_count >= 5:
        bonus += 1

    if not location_ok:
        bonus -= 1

    score = base + bonus
    return max(1, min(10, score))