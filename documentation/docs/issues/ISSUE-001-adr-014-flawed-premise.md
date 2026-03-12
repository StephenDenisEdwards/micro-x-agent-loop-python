# ISSUE-001: ADR-014 Is Based on a Flawed Premise

## Status

**Resolved** — ADR-014 rewritten and all 11 cross-references corrected in `4ebb728`. ADR-014 further updated to v3 (2026-03-12) reflecting that Option C has been implemented incrementally — see ADR-014 revision history.

## Summary

ADR-014 ("MCP Returns Unstructured Text — Constraint on Compiled Mode") and 11 documents cross-referencing it are based on an incorrect understanding of the MCP protocol. The ADR claims that MCP servers return unstructured text by protocol design, making structured data processing impossible in compiled mode. This is wrong.

## The Error

ADR-014 states:

> MCP servers return unstructured text content blocks. This is by design — the MCP specification defines content blocks as text intended for LLM consumption, not programmatic processing.

This is incorrect. MCP is a **JSON-RPC protocol**. Tool call results contain content blocks with a `text` field that is a string — but that string can contain valid JSON. Many MCP servers return structured JSON in their text content blocks. The protocol does not mandate human-readable prose.

## What Is Actually True

1. **MCP can return structured JSON.** The `text` field in a `TextContent` block is a string. That string can be `{"id": "123", "subject": "Hello"}` just as easily as `"ID: 123\n  Subject: Hello"`.

2. **Our `McpToolProxy` treats all results as plain text.** It extracts `.text` from content blocks and joins with newlines. It does not attempt to detect or preserve JSON structure.

3. **Our built-in tools explicitly flatten structured data to human-readable text.** The Gmail tools receive JSON from the Gmail API and format it as `f"ID: {msg['id']}\n  Date: {date}\n..."` before returning. This is a design choice in our tool implementations, not an MCP limitation.

The constraint described in ADR-014 is real — but it is **self-imposed by our tool implementations and proxy layer**, not imposed by the MCP protocol.

## Affected Documents

ADR-014 was cross-referenced into 11 documents. All references propagate the flawed premise:

| Document | Reference Added |
|---|---|
| ADR index (README.md) | ADR-014 entry |
| ADR-012 (layered cost reduction) | "Related" note |
| ADR-013 (tool result summarization) | "Related" note |
| PLAN-mode-selection-llm-classification.md | Phase 4 marked "Blocked" |
| Planning INDEX.md | Status note |
| PLAN-cost-reduction.md | Phase 3 note |
| Research paper (Section 9) | Limitation bullet |
| Engineering white paper (Section 9) | Risk bullet |
| Execution model design (Section 2.3) | Weakness + updated verdict |
| DESIGN-tool-system.md | Note on MCP tools |
| Agent loop tool calls | Summary note |

## Corrections Applied

1. **ADR-014** rewritten with corrected title ("Tool Results Are Unstructured Text — Design Choice Affecting Compiled Mode") and correction notice referencing this issue.

2. **All 11 cross-references** updated to state that unstructured text is a design choice in our tool implementations, not an MCP protocol limitation.

3. **The actual problem** — that our tools return human-readable text instead of structured JSON — is now documented accurately in the corrected ADR-014.

## Root Cause

The error originated from observing that `McpToolProxy.execute()` returns plain text strings and that built-in tools like Gmail format results as human-readable text. The incorrect leap was attributing this to the MCP protocol specification rather than to our implementation choices.

## Commits Affected

- `07ce35b` — ADR-014 created (flawed premise)
- `b8f3406` — 11 documents cross-referenced with flawed premise
- `4ebb728` — ADR-014 rewritten and all 11 cross-references corrected
