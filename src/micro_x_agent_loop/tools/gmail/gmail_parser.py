import base64


def get_header(headers: list[dict] | None, name: str) -> str:
    if not headers:
        return ""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def decode_body(data: str) -> str:
    """Decode Gmail's base64url-encoded body data."""
    padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def extract_text(payload: dict) -> str:
    """Recursively extract the best content from a message payload.

    For multipart/alternative, prefer HTML (richest representation).
    For other multipart types, concatenate all readable sub-parts.
    Returns raw HTML when available — the LLM can parse it directly.
    """
    body_data = payload.get("body", {}).get("data", "")
    mime_type = payload.get("mimeType", "")

    if body_data:
        if mime_type in ("text/plain", "text/html"):
            return decode_body(body_data)

    parts = payload.get("parts")
    if not parts:
        return ""

    # multipart/alternative — pick the richest version
    if mime_type == "multipart/alternative":
        for part in reversed(parts):
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                return decode_body(part["body"]["data"])

        for part in reversed(parts):
            if (part.get("mimeType") or "").startswith("multipart/"):
                text = extract_text(part)
                if text:
                    return text

        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return decode_body(part["body"]["data"])

    # multipart/mixed, multipart/related, etc.
    sections = []
    for part in parts:
        text = extract_text(part)
        if text:
            sections.append(text)
    return "\n\n".join(sections)
