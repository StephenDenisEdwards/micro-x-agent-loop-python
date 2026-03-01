# Adapt Template Console App

Adapt `tools/template/` into a console app that produces the same output as the agent loop would for the user prompt below — at near-zero cost.

**Project root:** `C:\Users\steph\source\repos\micro-x-agent-loop-python`
**Template location:** `C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\template`

## Rules

1. **Copy first, then code.** Your FIRST action must be to copy the template directory. If the target already exists, delete it first. Use absolute paths — bash may not run in the project root. NEVER modify files in `tools/template/` or any other existing directory. All new code goes in the copy only.
2. **NEVER edit `__main__.py`, `mcp_client.py`, `llm.py`, or `tools.py`.** These are infrastructure. They work. Do not touch them.
3. **No LLM API calls unless you can prove Python can't do it.** Scoring, ranking, filtering, counting, formatting, report generation — all Python. If you must use one, exactly one Haiku call. Justify it in a code comment.
4. **No documentation.** Do not create README, IMPLEMENTATION, QUICKSTART, SUMMARY, or any other non-code files. Only create `.py` files.
5. **Use relative imports.** (`from .tools import ...`, not `from tools import ...`). The app runs as `python -m tools.<task_name>`.
6. **Do not run the app.** Just write the code. The user will test it.
7. **Do not explore the codebase.** Everything you need is in the copied template and this prompt.
8. **Use `write_file()` for output.** Import from `.__main__`: `from .__main__ import write_file`. Pass `config` so relative paths resolve to `WorkingDirectory`.
9. **Use `tools.py` for all MCP calls.** Import from `.tools`. They handle server routing and error checking.

## Exact Steps

1. Copy the template using absolute paths:
   ```
   xcopy C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\template C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\<task_name> /E /I /Y
   ```
   Do NOT wrap paths in quotes. xcopy exit code 0 = success.
2. Read `tools.py` in your copy to see available MCP functions and their return types.
3. Read the user prompt below. Decide which functions from `tools.py` you need.
4. **Replace `task.py`** with your implementation:
   - Set `SERVERS` to the list of MCP server names you need (e.g. `["google", "linkedin"]`)
   - Implement `run_task(clients, config)` — this is your main entry point
   - Import helpers: `from .tools import ...` and `from .__main__ import write_file`
5. Create additional modules as needed (only the ones you need):
   - `collector.py` — async functions that call `tools.py` wrappers and return lists of dicts
   - `scorer.py` — pure Python scoring/ranking functions (no MCP, no LLM)
   - `processor.py` — report generation using f-strings (no LLM)
6. Do NOT edit `__main__.py`. Do NOT create any non-`.py` files. You are done.

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
