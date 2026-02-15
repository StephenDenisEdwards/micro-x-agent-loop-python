from html import unescape
from typing import Any

import httpx
from bs4 import BeautifulSoup

from micro_x_agent_loop.tools.html_utilities import html_to_text


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class LinkedInJobDetailTool:
    @property
    def name(self) -> str:
        return "linkedin_job_detail"

    @property
    def description(self) -> str:
        return (
            "Fetch the full job specification/description from a LinkedIn job URL. "
            "Use this after linkedin_jobs to get complete details for a specific posting."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The LinkedIn job URL (e.g. from a linkedin_jobs search result)",
                },
            },
            "required": ["url"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        url = tool_input["url"]
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=_HEADERS)

            if response.status_code != 200:
                return f"Error fetching job page: HTTP {response.status_code}"

            soup = BeautifulSoup(response.text, "lxml")

            title_el = (
                soup.find("h1", class_=lambda c: c and "top-card-layout__title" in c)
                or soup.find("h1")
            )
            company_el = (
                soup.find("a", class_=lambda c: c and "topcard__org-name-link" in c)
                or soup.find(class_=lambda c: c and "top-card-layout__company-name" in c)
            )
            location_el = (
                soup.find("span", class_=lambda c: c and "topcard__flavor--bullet" in c)
                or soup.find("span", class_=lambda c: c and "top-card-layout__bullet" in c)
            )

            desc_el = (
                soup.find(class_=lambda c: c and "description__text" in c)
                or soup.find(class_=lambda c: c and "show-more-less-html__markup" in c)
                or soup.find(class_=lambda c: c and "decorated-job-posting__details" in c)
            )

            description = ""
            if desc_el:
                description = html_to_text(str(desc_el))

            if not description.strip():
                return (
                    "Could not extract job description from the page. "
                    "LinkedIn may have blocked the request or the page structure has changed."
                )

            parts = []
            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else ""

            if title:
                parts.append(f"Title: {unescape(title)}")
            if company:
                parts.append(f"Company: {unescape(company)}")
            if location:
                parts.append(f"Location: {unescape(location)}")
            parts.append("")
            parts.append("--- Job Description ---")
            parts.append("")
            parts.append(description)

            return "\n".join(parts)

        except Exception as ex:
            return f"Error fetching job details: {ex}"
