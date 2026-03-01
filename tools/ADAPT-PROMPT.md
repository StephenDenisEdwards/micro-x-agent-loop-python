# Adapt Template Console App

You will create a console app by copying a template and writing task-specific code.
The template already contains working infrastructure (`__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, `utils.py`). You only need to write `task.py` and optionally `collector.py`, `scorer.py`, `processor.py`.

---

## Step 1 — Copy the template

Choose a short snake_case name for the task (e.g. `job_search`). Then run this command, replacing `<task_name>` with your chosen name:

```
xcopy C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\template C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\<task_name> /E /I /Y
```

Do NOT wrap the paths in quotes. Exit code 0 means success.

If the target directory already exists, delete it first:
```
rmdir /s /q C:\Users\steph\source\repos\micro-x-agent-loop-python\tools\<task_name>
```

After copying, list the directory to confirm these files exist:
- `__init__.py`, `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, `utils.py`, `task.py`

**If these files are missing, STOP. The copy failed.**

## Step 2 — Read tools.py

Read `tools.py` in your copy. It contains typed wrapper functions for all MCP tools. These are the ONLY functions you should use to call MCP servers. A summary:

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

## Step 3 — Read the user prompt

The user prompt describes what the app should do. Read it from this file:

```
C:\Users\steph\source\repos\resources\documents\job-search-prompt.txt
```

This file contains the full requirements: what data to collect, how to score it, and the exact report format. Read it carefully before writing any code.

## Step 4 — Write task.py

Replace the placeholder `task.py` with your implementation. This is the ONLY file you MUST write. It needs exactly two things:

```python
SERVERS = ["google", "linkedin"]  # MCP server names you need

async def run_task(clients: dict, config: dict) -> None:
    # Your implementation here
    pass
```

`__main__.py` imports `SERVERS` and `run_task` from `task.py`. It handles everything else (config loading, MCP connections, shutdown).

**Imports you can use in task.py:**
```python
from .tools import gmail_search, gmail_read, linkedin_search_with_details  # MCP wrappers
from .utils import write_file  # UTF-8 file writer, resolves relative paths via config
```

**Writing output files:**
```python
from .utils import write_file
write_file("todays-jobs-2026-03-01.md", report_markdown, config)
```
Always pass `config` so relative paths resolve to the WorkingDirectory.

## Step 5 — Create helper modules (optional)

If the task is complex, split logic into separate files. Only create the ones you need:

- `collector.py` — async functions that call `tools.py` wrappers and return `list[dict]`
- `scorer.py` — pure Python scoring/ranking (no MCP, no LLM)
- `processor.py` — report generation using f-strings (no LLM)

All scoring, ranking, filtering, counting, statistics, and report formatting MUST be pure Python. Do not use LLM calls for these. Use `re`, `collections.Counter`, `statistics.mean`, `sorted()`, f-strings.

## Step 6 — Verify and stop

You are done when `task.py` (and any helpers) are written. Confirm:

- [ ] `task.py` exports `SERVERS` (list of strings) and `run_task(clients, config)`
- [ ] All MCP calls go through `tools.py` wrappers (`from .tools import ...`)
- [ ] All file output uses `write_file` from `utils.py` (`from .utils import write_file`)
- [ ] All imports are relative (`from .tools`, not `from tools`)
- [ ] `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, `utils.py` are UNTOUCHED
- [ ] No non-`.py` files were created (no README, no .md, no .bat, no .txt)

**Do NOT run the app.** The user will test it.

---

## Rules (mandatory)

1. **Copy first.** Your very first action is the xcopy command. Do not write any code before the copy succeeds.
2. **Never edit infrastructure files.** `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, `utils.py` — do not touch these. They are tested and working.
3. **Never modify files outside your copy.** Do not edit anything in `tools/template/` or anywhere else.
4. **No LLM calls** unless you can prove Python cannot do it. If you must use one, use exactly one Haiku call and justify it in a code comment.
5. **No documentation files.** Only create `.py` files. No README, IMPLEMENTATION, QUICKSTART, SUMMARY, or any other non-code file.
6. **Do not run the app.** Write the code and stop.
7. **Do not explore the codebase.** Everything you need is in your copied template, `tools.py`, and this prompt.
8. **Use relative imports only.** The app runs as `python -m tools.<task_name>`.

---

## The User Prompt to Implement

Read this file for the full task requirements:

```
C:\Users\steph\source\repos\resources\documents\job-search-prompt.txt
```
