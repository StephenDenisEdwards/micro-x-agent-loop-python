# Design: Tool System

## Overview

The tool system provides Claude with the ability to interact with the outside world. Each tool is a self-contained unit that accepts a dict input, performs an action, and returns a string result.

## Tool Protocol

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    async def execute(self, tool_input: dict[str, Any]) -> str: ...
```

| Member | Purpose |
|--------|---------|
| `name` | Unique identifier sent to Claude (e.g., `"read_file"`) |
| `description` | Natural-language description Claude uses to decide when to call the tool |
| `input_schema` | JSON Schema dict defining the expected input parameters |
| `execute` | Executes the tool and returns a string result |

Using `typing.Protocol` provides structural typing — any class with matching properties and methods satisfies the interface without explicit inheritance.

## Tool Registry

`tool_registry.get_all()` assembles the tool list with their dependencies:

```python
def get_all(
    working_directory: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
) -> list[Tool]:
```

Gmail tools are **conditionally registered** — they are only added when both Google credentials are present. This prevents runtime errors when Gmail is not configured.

## Built-in Tools

### File System

| Tool | Description |
|------|-------------|
| `read_file` | Read text files and `.docx` documents. Resolves relative paths against the configured `WorkingDirectory`. |
| `write_file` | Write content to a file, creating parent directories as needed. Resolves relative paths against `WorkingDirectory`. |

### Shell

| Tool | Description |
|------|-------------|
| `bash` | Execute a shell command (cmd.exe on Windows, bash on Unix). 30-second timeout. Uses `WorkingDirectory` as the current working directory. |

### LinkedIn

| Tool | Description |
|------|-------------|
| `linkedin_jobs` | Search LinkedIn job postings by keyword, location, date, job type, remote filter, experience level, and sort order. Scrapes the public jobs API. |
| `linkedin_job_detail` | Fetch the full job description from a LinkedIn job URL. |

### Gmail (conditional)

| Tool | Description |
|------|-------------|
| `gmail_search` | Search Gmail using Gmail search syntax (e.g., `is:unread`, `from:someone@example.com`). |
| `gmail_read` | Read the full content of a Gmail message by its ID. Returns raw HTML for the LLM to process. |
| `gmail_send` | Send a plain-text email. |

Gmail tools require OAuth2 authentication. On first use, a browser window opens for Google sign-in. Tokens are cached in `.gmail-tokens/`.

## Shared Utilities

### HtmlUtilities

`html_utilities.html_to_text(html)` converts HTML to readable plain text. Used by LinkedIn tools for job description extraction.

Handles:
- Block elements (p, div, h1-h6, blockquote, tr) with newlines
- Link URL preservation (`<a href="url">text</a>` becomes `text (url)`)
- List items with bullet markers
- Table cells with tab separation
- Script/style removal
- HTML entity decoding
- Whitespace normalization

### GmailParser

- `decode_body` — base64url decoding for Gmail message bodies
- `extract_text` — recursive MIME parsing, prefers HTML over plain text for multipart/alternative
- `get_header` — case-insensitive header lookup

## Adding a New Tool

1. Create a class in the `tools/` directory with matching `Tool` Protocol members
2. Define `name`, `description`, and `input_schema` properties
3. Implement `async execute()` with error handling (return error strings, don't raise)
4. Register it in `tool_registry.get_all()`

Example skeleton:

```python
from typing import Any


class MyTool:
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",
                    "description": "A required parameter",
                }
            },
            "required": ["param"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        param = tool_input["param"]
        try:
            # Do work
            return "Result"
        except Exception as ex:
            return f"Error: {ex}"
```
