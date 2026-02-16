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

Each tool has its own detailed documentation in the [tools/](tools/) directory.

### File System

| Tool | Description | Docs |
|------|-------------|------|
| `read_file` | Read text files and `.docx` documents | [read-file](tools/read-file/README.md) |
| `write_file` | Write content to a file, creating directories as needed | [write-file](tools/write-file/README.md) |

### Shell

| Tool | Description | Docs |
|------|-------------|------|
| `bash` | Execute a shell command (cmd.exe on Windows, bash on Unix) | [bash](tools/bash/README.md) |

### LinkedIn

| Tool | Description | Docs |
|------|-------------|------|
| `linkedin_jobs` | Search LinkedIn job postings with filters | [linkedin-jobs](tools/linkedin-jobs/README.md) |
| `linkedin_job_detail` | Fetch full job description from a LinkedIn URL | [linkedin-job-detail](tools/linkedin-job-detail/README.md) |

### Gmail (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `gmail_search` | Search Gmail using Gmail search syntax | [gmail-search](tools/gmail-search/README.md) |
| `gmail_read` | Read full email content by message ID | [gmail-read](tools/gmail-read/README.md) |
| `gmail_send` | Send a plain-text email | [gmail-send](tools/gmail-send/README.md) |

Gmail tools require OAuth2 authentication. On first use, a browser window opens for Google sign-in. Tokens are cached in `.gmail-tokens/`. See [ADR-004](../architecture/decisions/ADR-004-raw-html-for-gmail.md) for the decision to pass raw HTML to the LLM.

### Google Calendar (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `calendar_list_events` | List events by date range or search query | [calendar-list-events](tools/calendar-list-events/README.md) |
| `calendar_create_event` | Create events with title, time, attendees | [calendar-create-event](tools/calendar-create-event/README.md) |
| `calendar_get_event` | Get full event details by ID | [calendar-get-event](tools/calendar-get-event/README.md) |

Calendar tools use the same Google OAuth2 credentials as Gmail but with a separate token cache (`.calendar-tokens/`) and the `https://www.googleapis.com/auth/calendar` scope.

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
