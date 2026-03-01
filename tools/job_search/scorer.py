"""Single Haiku API call for job scoring and report generation."""

import json
from datetime import date
from typing import Any

import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 16384


async def score_and_report(
    jobserve_jobs: list[dict[str, Any]],
    linkedin_jobs: list[dict[str, Any]],
    criteria: str,
    prompt_template: str,
) -> str:
    """Score all jobs and generate the complete markdown report in a single API call."""
    today = date.today().strftime("%B %d, %Y")
    today_iso = date.today().isoformat()

    system_prompt = f"""You are a job search analyst. Today's date is {today}.

You will receive job data collected from Gmail (JobServe) and LinkedIn, along with the candidate's search criteria and a report format template.

Your task:
1. Score each job against the search criteria (1-10 scale)
2. Exclude jobs scoring below 5
3. Generate a complete markdown report following the exact format specified

{criteria}

{prompt_template}

IMPORTANT:
- Output ONLY the markdown report, no preamble or explanation
- Use the exact section structure from the template
- Include HTML anchor tags for Top 10 cross-references
- File should be named todays-jobs-{today_iso}.md
- Report date: {today}"""

    # Build the user message with all job data
    job_data = {
        "jobserve_emails": jobserve_jobs,
        "linkedin_jobs": linkedin_jobs,
    }

    user_message = f"""Here is the collected job data. Score each job and generate the complete markdown report.

JOB DATA:
{json.dumps(job_data, indent=2, default=str)}"""

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract text from response
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)

    report = "\n".join(text_parts)

    # Log token usage
    usage = response.usage
    input_cost = usage.input_tokens * 0.80 / 1_000_000
    output_cost = usage.output_tokens * 4.00 / 1_000_000
    total_cost = input_cost + output_cost
    print(f"  LLM usage: {usage.input_tokens:,} input + {usage.output_tokens:,} output tokens")
    print(f"  Estimated cost: ${total_cost:.4f} (input: ${input_cost:.4f}, output: ${output_cost:.4f})")

    return report
