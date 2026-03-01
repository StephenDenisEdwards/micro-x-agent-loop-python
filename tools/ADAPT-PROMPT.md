# Adapt Template Console App

Adapt `tools/template/` into a console app that produces the same output as the agent loop would for the user prompt below — at near-zero cost.

**Project root:** `C:\Users\steph\source\repos\micro-x-agent-loop-python`
**Template location:** `C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\template`

## Rules

1. **Copy first, then code.** Your FIRST action must be to copy the template directory. If the target already exists, delete it first. Use absolute paths — bash may not run in the project root. NEVER modify files in `tools/template/` or any other existing directory. All new code goes in the copy only.
2. **No LLM API calls unless you can prove Python can't do it.** Scoring, ranking, filtering, counting, formatting, report generation — all Python. The LLM is only for irreducible natural language generation (synthesising unstructured free-text into prose that no template can produce). If you must use one, exactly one Haiku call. Justify it in a code comment.
3. **No documentation.** Do not create README, IMPLEMENTATION, QUICKSTART, SUMMARY, or any other non-code files. No docstrings beyond one-liners. No comments explaining obvious code. Only create `.py` files.
4. **Only connect MCP servers the task actually uses.**
5. **Use relative imports.** All imports between modules in your package must use relative imports (`from .tools import ...`, not `from tools import ...`). The app runs as `python -m tools.<task_name>` which requires this.
6. **Do not run the app.** Just write the code. The user will test it.
7. **Do not explore the codebase.** Everything you need is in the copied template and this prompt. Read only the files in your copy. Do not search, grep, or browse any other directory.
8. **Use `write_file(filename, content, config)` from `__main__.py`** to write output files. Pass `config` so relative paths resolve to `WorkingDirectory`. Do not use `open()` directly for output.
9. **Use `tools.py` for all MCP calls.** Do not call `client.call_tool()` directly. Import functions from `.tools` instead. They handle server routing, error checking, and response parsing.

## Exact Steps

1. Copy the template using absolute paths:
   ```
   robocopy "C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\template" "C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\<task_name>" /E
   ```
   (robocopy exit code 1 = success on Windows)
2. Read `tools.py` in your copy to see available MCP functions and their return types.
3. Read the user prompt below. Decide which functions from `tools.py` you need and what Python logic to write.
4. Create these files in your copy (only the ones you need), using `write_file` or `read_file` with absolute paths:
   - `collector.py` — async functions that call `tools.py` wrappers and return lists of dicts
   - `scorer.py` — pure Python scoring/ranking functions (no MCP, no LLM)
   - `processor.py` — report generation using f-strings (no LLM)
5. Edit `__main__.py`:
   - Import your new modules with relative imports
   - Filter `mcp_configs` to only needed servers in `main()`
   - Replace `run_task()` body with: collect → score → generate report → write file
   - Remove `discover_tools()` and `print_tool_catalog()` calls (not needed)
6. Do NOT create any other files. You are done.

## Available MCP Functions (tools.py)

All functions take `clients` dict as first arg. Import with `from .tools import gmail_search, linkedin_search, ...`

**Gmail** (server: `google`):
- `gmail_search(clients, query, max_results=10)` → `list[{id, date, from, subject, snippet}]`
- `gmail_read(clients, message_id)` → `{messageId, from, to, date, subject, body}` or `None`
- `gmail_send(clients, to, subject, body)` → status text

**LinkedIn** (server: `linkedin`):
- `linkedin_search(clients, keyword, location, date_posted, job_type, experience, limit, sort_by)` → `list[{index, title, company, location, posted, salary, url}]`
- `linkedin_detail(clients, url)` → `{title, company, location, description, url}` or `None`
- `linkedin_search_with_details(clients, keyword, limit, batch_size, **kwargs)` → `list[{...job, detail: {title, company, location, description, url}}]`

**Web** (server: `web`):
- `web_search(clients, query, count=5)` → `list[{title, url, description}]`
- `web_fetch(clients, url, max_chars=50000)` → `{url, content, content_length, ...}` or `None`

**Filesystem** (server: `filesystem`):
- `fs_read(clients, path)` → content string or `None`
- `fs_write(clients, path, content)` → `True`/`False`
- `fs_bash(clients, command)` → `{stdout, stderr, exit_code}`

## Python-First Alternatives

Before reaching for the LLM, use these:

| Task | Python alternative |
|------|-------------------|
| Scoring/ranking | Weighted function: keyword match (`re`, `in`), numeric comparison, `sorted()` |
| Report/markdown generation | f-strings, Jinja2 templates |
| Statistics/aggregation | `collections.Counter`, `statistics.mean`, comprehensions |
| Text extraction/parsing | `re`, `BeautifulSoup`, field access on structured data |
| Fuzzy matching | `rapidfuzz`, `difflib.SequenceMatcher` |
| Date/time | `datetime`, `dateutil.parser` |
| "Why this score" prose | Template: `f"Matches {n} techs ({techs}). {rate_note}."` |
| "Key Observations" | Derive from data: `f"{pct}% of roles are contract"` |
| "Recommendations" | Sort by score: `f"Apply to {title} — highest match at {score}/10"` |

## Patterns

**Data collection using tools.py:**
```python
from .tools import gmail_search, gmail_read, linkedin_search_with_details

emails = await gmail_search(clients, "from:jobserve.com newer_than:1d", max_results=50)
for msg in emails:
    full = await gmail_read(clients, msg["id"])
    if full:
        process(full)

jobs = await linkedin_search_with_details(clients, keyword=".NET Azure", limit=15, location="United Kingdom")
```

**LLM fallback (only if unavoidable):**
```python
from .llm import create_message, estimate_cost
text, usage = await create_message(
    model="claude-haiku-4-5-20251001", max_tokens=16384,
    system="...", messages=[{"role": "user", "content": json.dumps(data)}],
)
```

---

## The User Prompt to Implement

```
Located in file: C:\Users\steph\source\repos\resources\documents\job-search-prompt.txt
```
