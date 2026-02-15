from html import unescape
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_DATE_FILTER_MAP = {
    "24hr": "r86400",
    "past week": "r604800",
    "past month": "r2592000",
}


class LinkedInJobsTool:
    @property
    def name(self) -> str:
        return "linkedin_jobs"

    @property
    def description(self) -> str:
        return "Search for job postings on LinkedIn. Returns job title, company, location, date, salary, and URL."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Job search keyword (e.g. 'software engineer')",
                },
                "location": {
                    "type": "string",
                    "description": "Job location (e.g. 'New York', 'Remote')",
                },
                "dateSincePosted": {
                    "type": "string",
                    "description": "Recency filter: 'past month', 'past week', or '24hr'",
                },
                "jobType": {
                    "type": "string",
                    "description": "Employment type: 'full time', 'part time', 'contract', 'temporary', 'internship'",
                },
                "remoteFilter": {
                    "type": "string",
                    "description": "Work arrangement: 'on site', 'remote', or 'hybrid'",
                },
                "experienceLevel": {
                    "type": "string",
                    "description": "Experience level: 'internship', 'entry level', 'associate', 'senior', 'director', 'executive'",
                },
                "limit": {
                    "type": "string",
                    "description": "Max number of results to return (default '10')",
                },
                "sortBy": {
                    "type": "string",
                    "description": "Sort order: 'recent' or 'relevant'",
                },
            },
            "required": ["keyword"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            keyword = tool_input["keyword"]
            location = tool_input.get("location")
            limit_str = tool_input.get("limit", "10")
            limit = int(limit_str) if limit_str else 10
            date_since_posted = tool_input.get("dateSincePosted")
            sort_by = tool_input.get("sortBy")

            date_filter = _DATE_FILTER_MAP.get(date_since_posted, "") if date_since_posted else ""
            sort_param = "&sortBy=DD" if sort_by == "recent" else ""

            encoded_keyword = quote(keyword)
            encoded_location = quote(location) if location else ""

            url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                f"keywords={encoded_keyword}"
            )
            if encoded_location:
                url += f"&location={encoded_location}"
            if date_filter:
                url += f"&f_TPR={date_filter}"
            url += f"&start=0&count={limit}{sort_param}"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers={"User-Agent": _USER_AGENT})

            if response.status_code != 200:
                return f"Error fetching LinkedIn jobs: HTTP {response.status_code}"

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.find_all("li")

            if not cards:
                return "No job postings found matching your criteria."

            results = []
            index = 0
            for card in cards:
                if index >= limit:
                    break

                title_el = card.find("h3", class_=lambda c: c and "base-search-card__title" in c)
                company_el = card.find("h4", class_=lambda c: c and "base-search-card__subtitle" in c)
                loc_el = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
                posted_el = card.find("time")
                salary_el = card.find("span", class_=lambda c: c and "job-search-card__salary" in c)
                url_el = card.find("a", class_=lambda c: c and "base-card__full-link" in c)

                title = title_el.get_text(strip=True) if title_el else None
                if title is None:
                    continue

                company = company_el.get_text(strip=True) if company_el else ""
                loc = loc_el.get_text(strip=True) if loc_el else ""
                posted = posted_el.get_text(strip=True) if posted_el else ""
                salary = salary_el.get_text(strip=True) if salary_el else "Not listed"
                job_url = url_el["href"] if url_el else ""

                index += 1
                results.append(
                    f"{index}. {unescape(title)}\n"
                    f"   Company: {unescape(company)}\n"
                    f"   Location: {unescape(loc)}\n"
                    f"   Posted: {posted}\n"
                    f"   Salary: {salary}\n"
                    f"   URL: {job_url}"
                )

            return "\n\n".join(results) if results else "No job postings found matching your criteria."

        except Exception as ex:
            return f"Error searching LinkedIn jobs: {ex}"
