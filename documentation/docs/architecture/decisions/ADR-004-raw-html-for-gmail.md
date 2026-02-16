# ADR-004: Raw HTML for Gmail Email Content

## Status

Accepted

## Context

The `gmail_read` tool retrieves email content from the Gmail API, which returns HTML-formatted bodies for most emails. The initial implementation used `html_to_text()` (a BeautifulSoup-based converter) to strip HTML and return plain text to the LLM.

This caused a significant problem: **links and URLs were lost** during conversion. Email content frequently contains important links (unsubscribe links, meeting URLs, document links, action buttons) that the user may need. Converting to plain text discarded this information.

Options considered:

1. **Plain text conversion with link preservation** — modify `html_to_text()` to preserve `<a href>` URLs inline (e.g., `text (url)`)
2. **Raw HTML to LLM** — pass the decoded HTML directly to the LLM without conversion
3. **Markdown conversion** — convert HTML to Markdown to preserve structure and links

## Decision

Pass **raw HTML** from Gmail emails directly to the LLM. The `gmail_parser.extract_text()` function decodes the base64url-encoded body and returns the HTML as-is, without calling `html_to_text()`.

The `html_to_text()` utility remains in the codebase for use by LinkedIn tools, which still benefit from text conversion (job descriptions don't need link-heavy parsing by the LLM).

## Consequences

**Easier:**
- All email content is preserved — links, formatting, tables, embedded styles
- The LLM (Claude) is fully capable of parsing and understanding HTML
- No information loss compared to the original email
- Simpler code path — no conversion step for email content

**Harder:**
- HTML content uses more tokens than equivalent plain text
- Some emails have verbose or messy HTML (marketing emails with tracking pixels, inline CSS)
- Large HTML emails may hit the `MaxToolResultChars` truncation limit more easily
