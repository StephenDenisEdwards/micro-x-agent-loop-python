import re
from html import unescape

from bs4 import BeautifulSoup, NavigableString, Tag


def html_to_text(html: str) -> str:
    """Convert an HTML string to readable plain text.

    Handles block elements, lists, table cells, and whitespace normalization.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove non-visible elements
    for tag in soup.find_all(["script", "style", "head"]):
        tag.decompose()

    # Replace <br> with newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # Add newlines around block elements
    for tag in soup.find_all(["p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]):
        tag.insert(0, NavigableString("\n"))
        tag.append(NavigableString("\n"))

    # Preserve link URLs: <a href="url">text</a> → text (url)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        link_text = a.get_text(strip=True)
        if href and href != link_text and not href.startswith("#"):
            a.replace_with(f"{link_text} ({href})" if link_text else href)

    # Bullet list items
    for li in soup.find_all("li"):
        li.insert(0, NavigableString("\n- "))

    # Table cells
    for td in soup.find_all(["td", "th"]):
        td.append(NavigableString("\t"))

    # Get the body text (or full text if no body)
    body = soup.find("body")
    text = (body or soup).get_text()
    text = unescape(text)

    # Normalize whitespace
    text = re.sub(r"\t+", "  ", text)
    text = re.sub(r" {3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
