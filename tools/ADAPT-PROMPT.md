# Adapt Template Console App

Adapt `tools/template/` into a console app that produces the same output as the agent loop would for the user prompt below — at near-zero cost.

## Rules

1. **Copy first, then code.** Your FIRST action must be `cp -r tools/template tools/<task_name>`. NEVER modify files in `tools/template/` or any other existing directory. All new code goes in the copy only.
2. **No LLM API calls unless you can prove Python can't do it.** Scoring, ranking, filtering, counting, formatting, report generation — all Python. The LLM is only for irreducible natural language generation (synthesising unstructured free-text into prose that no template can produce). If you must use one, exactly one Haiku call. Justify it in a code comment.
3. **No documentation.** Do not create README, IMPLEMENTATION, QUICKSTART, SUMMARY, or any other non-code files. No docstrings beyond one-liners. No comments explaining obvious code. Only create `.py` files.
4. **Only connect MCP servers the task actually uses.**
5. **Use relative imports.** All imports between modules in your package must use relative imports (`from .scorer import ...`, not `from scorer import ...`). The app runs as `python -m tools.<task_name>` which requires this.
6. **Do not run the app.** Just write the code. The user will test it.
7. **Do not explore the codebase.** Everything you need is in `tools/template/` (already copied) and this prompt. Read only the files in your copy. Do not search, grep, or browse any other directory.

## Exact Steps

1. `cp -r tools/template tools/<task_name>`
2. Read the user prompt below. Decide which MCP tools you need and what Python logic to write.
3. Create these files in `tools/<task_name>/` (only the ones you need):
   - `collector.py` — async functions that call MCP tools and return lists of dicts
   - `scorer.py` — pure Python scoring/ranking functions (no MCP, no LLM)
   - `processor.py` — report generation using f-strings (no LLM)
4. Edit `__main__.py`:
   - Import your new modules with relative imports
   - Filter `mcp_configs` to only needed servers in `main()`
   - Replace `run_task()` body with: collect → score → generate report → write file
   - Remove `discover_tools()` and `print_tool_catalog()` calls (not needed)
5. Do NOT create any other files. You are done.

## structuredContent Shapes

`call_tool()` returns a dict (structuredContent) or str (text fallback). Check `isinstance(result, str)`. Never `json.loads()` on results. Key return shapes:

| Tool | structuredContent fields |
|------|------------------------|
| `gmail_search` | `{ messages: [{ id, date, from, subject, snippet }], total_found }` |
| `gmail_read` | `{ messageId, from, to, date, subject, body }` |
| `linkedin_jobs` | `{ jobs: [{ index, title, company, location, posted, salary, url }], total_found }` |
| `linkedin_job_detail` | `{ title, company, location, description, url }` |
| `web_search` | `{ results: [{ title, url, description }], total_found }` |
| `web_fetch` | `{ url, content, contentLength }` |

For other tools, run `python -m tools.template` for the full catalog or read `tools/template/README.md`.

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

**Data collection:**
```python
result = await client.call_tool("tool_name", {"arg": "value"})
if isinstance(result, str):
    return []
items = result.get("items", [])
```

**Parallel detail fetching:**
```python
for i in range(0, len(items), 5):
    batch = items[i:i + 5]
    results = await asyncio.gather(*(fetch_detail(client, x) for x in batch))
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
