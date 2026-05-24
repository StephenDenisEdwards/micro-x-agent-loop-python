---
name: feedback-bash-tool-uses-posix-not-powershell
description: The Bash tool runs POSIX bash even though the interactive shell is PowerShell — use POSIX syntax in Bash tool calls
metadata:
  type: feedback
---

The environment context for this project says "Shell: PowerShell (use PowerShell syntax)". That guidance is for the *interactive* shell only. The **Bash tool runs `/usr/bin/bash`** (confirmed by an error: `/usr/bin/bash: line 1`). Using PowerShell syntax in a Bash tool call (e.g. `$env:VAR=1; cmd`) fails silently-ish — the env var is not set and the command misbehaves.

**Why:** Wasted a live, money-costing eval run (`tests/evals/test_rss_count.py`) because `$env:MICRO_X_RUN_EVALS=1;` was parsed as bash, so the var never set and the test skipped.

**How to apply:** In Bash tool calls always use POSIX syntax — `VAR=value command`, `$VAR`, `2>/dev/null`, `&&`. Reserve PowerShell syntax (`$env:`, `$null`) for commands the user runs in their interactive shell. Don't blindly apply the "Shell: PowerShell" environment note to the Bash tool.
