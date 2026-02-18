import json
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from micro_x_agent_loop.tools.html_utilities import html_to_text

_DEFAULT_MAX_CHARS = 50_000
_MAX_RESPONSE_BYTES = 2_000_000  # 2 MB
_TIMEOUT_SECONDS = 30
_MAX_REDIRECTS = 5

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class WebFetchTool:
    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch content from a URL and return it as readable text. "
            "Supports HTML pages (converted to plain text with links preserved), "
            "JSON APIs (pretty-printed), and plain text. GET requests only."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The HTTP or HTTPS URL to fetch",
                },
                "maxChars": {
                    "type": "number",
                    "description": (
                        "Maximum characters of content to return (default 50000). "
                        "Content beyond this limit is truncated with a notice."
                    ),
                },
            },
            "required": ["url"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        url: str = tool_input["url"]
        max_chars: int = int(tool_input.get("maxChars", _DEFAULT_MAX_CHARS))

        # Validate URL scheme
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "Error: URL must use http or https scheme"

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                timeout=_TIMEOUT_SECONDS,
                follow_redirects=True,
                max_redirects=_MAX_REDIRECTS,
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException:
            return f"Error: Request timed out after {_TIMEOUT_SECONDS} seconds"
        except httpx.TooManyRedirects:
            return f"Error: Too many redirects (max {_MAX_REDIRECTS})"
        except httpx.HTTPError as ex:
            return f"Error: {ex}"

        if response.status_code >= 400:
            return f"Error: HTTP {response.status_code} fetching {url}"

        # Reject oversized responses
        content_length = len(response.content)
        if content_length > _MAX_RESPONSE_BYTES:
            return (
                f"Error: Response too large ({content_length:,} bytes, "
                f"max {_MAX_RESPONSE_BYTES:,} bytes)"
            )

        content_type = response.headers.get("content-type", "")
        final_url = str(response.url)

        # Extract content based on content type
        title = ""
        if "text/html" in content_type or "application/xhtml" in content_type:
            soup = BeautifulSoup(response.text, "lxml")
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            content = html_to_text(response.text)
        elif "application/json" in content_type:
            try:
                content = json.dumps(response.json(), indent=2)
            except (json.JSONDecodeError, ValueError):
                content = response.text
        else:
            content = response.text

        # Truncate if needed
        original_length = len(content)
        truncated = False
        if original_length > max_chars:
            content = content[:max_chars]
            truncated = True

        # Build metadata header
        parts = [f"URL: {url}"]
        if final_url != url:
            parts.append(f"Final URL: {final_url}")
        parts.append(f"Status: {response.status_code}")
        parts.append(f"Content-Type: {content_type}")
        if title:
            parts.append(f"Title: {title}")

        length_str = f"{original_length:,} chars"
        if truncated:
            length_str = f"{max_chars:,} chars (truncated from {original_length:,})"
        parts.append(f"Length: {length_str}")

        parts.append("")
        parts.append("--- Content ---")
        parts.append("")
        parts.append(content)

        if truncated:
            parts.append("")
            parts.append(f"[Content truncated at {max_chars:,} characters]")

        return "\n".join(parts)
