# Codegen Parameterisation — Manual Test Plan (Step 1)

Tests whether the agent reliably proposes a parameter/profile split before calling `generate_code`. This validates the system prompt directive added in Step 1 of `PLAN-codegen-parameterisation.md`.

## What to Look For

On every test, check:

1. **Does the agent propose before generating?** It should NOT call `generate_code` immediately.
2. **Is the proposal in the expected format?** Run parameters (name, type, default, description), profile structure, constants.
3. **Is the format consistent across tests?** Same structure, same level of detail.
4. **Is the param/profile split sensible?** Run params = things that vary per execution. Profile = user identity / preferences.
5. **Does it handle feedback?** When you push back, does it re-present an updated proposal?
6. **Does it skip when appropriate?** Simple one-off prompts should go straight to generation.

---

## Test 1: Complex Multi-Source Job Search (Reference Prompt)

**Prompt:**
```
Generate a reusable job search app from job-search-prompt-v3.txt
```

**Expected behaviour:** Agent reads the file, then proposes. Should NOT generate immediately.

**Expected run params:**
- `days` (number, default 1) — how far back to search
- `outputDir` or `outputFile` (string) — where to write the report

**Expected profile:**
- Candidate profile (title, experience, location, contract preference)
- Skills grouped by category
- Target roles
- Rate range and IR35 preference
- Sources (jobserve, indeed, cwjobs, jobleads, linkedin)
- Exclusion rules
- High-value keywords
- Scoring thresholds

**Expected constants:**
- Scoring logic, report format, link rewriting rules, write-then-append strategy

**Follow-up test:** After the proposal, say: "Move sources to run params. Add maxResults as a run param." Verify the agent re-presents with those changes.

---

## Test 2: Simple Email Summary

**Prompt:**
```
Generate a reusable app that reads my last N emails and creates an email-summary.md file summarising each one with sender, subject, date, and a one-line summary.
```

**Expected run params:**
- `count` (number, default 20) — how many emails to fetch
- `outputFile` (string, default "email-summary.md")

**Expected profile:** Minimal or none — this task isn't user-specific.

**Expected constants:**
- Summary format, write-then-append strategy

**What to watch for:** Does the agent over-parameterise? There's no scoring, no user profile, no exclusions. The proposal should be simple.

---

## Test 3: Calendar Daily Briefing

**Prompt:**
```
Generate a reusable app that fetches my calendar events for the next N days and creates a daily-briefing.md with each day's events formatted as a schedule, including event title, time, location, and attendees.
```

**Expected run params:**
- `days` (number, default 1) — how many days ahead to look
- `outputFile` (string, default "daily-briefing.md")

**Expected profile:** Minimal — maybe calendar selection if multiple calendars exist.

**Expected constants:**
- Schedule formatting, time zone handling

---

## Test 4: GitHub Repository Health Report

**Prompt:**
```
Generate a reusable app that checks a GitHub repository for health metrics: open PRs older than 7 days, issues without labels, issues without assignees, and stale issues (no activity in 30 days). Write a health-report.md with sections for each category.
```

**Expected run params:**
- `repo` (string) — owner/repo to check
- `staleDays` (number, default 30) — threshold for stale issues
- `prAgeDays` (number, default 7) — threshold for old PRs
- `outputFile` (string, default "health-report.md")

**Expected profile:** Minimal — no user-specific preferences.

**Expected constants:**
- Report format, section structure

**What to watch for:** Does the agent correctly identify `repo` as a run param (changes per call) rather than profile? Does it avoid over-parameterising (e.g. making "issues without labels" a toggle)?

---

## Test 5: Multi-Source Research with Scoring

**Prompt:**
```
Generate a reusable app that researches a topic by:
1. Searching the web for recent articles (last 7 days)
2. Searching GitHub for relevant repos
3. Scoring each source on relevance (1-10) based on keyword matches against a topic profile
4. Writing a research-report.md ranked by score, with links and summaries

The topic for now: "MCP servers for AI agents" with keywords: MCP, Model Context Protocol, tool use, function calling, agent frameworks, LangChain, Claude
```

**Expected run params:**
- `days` (number, default 7) — how far back to search
- `maxResults` (number) — how many sources to fetch
- `outputFile` (string, default "research-report.md")

**Expected profile:**
- Topic name
- Keywords list
- Scoring thresholds (what counts as high/medium/low relevance)
- Minimum score cutoff

**Expected constants:**
- Scoring logic, report format, source ranking

**What to watch for:** This is structurally similar to the job search (multi-source + scoring + profile). Does the agent recognise the pattern and propose a similar split?

---

## Test 6: LinkedIn Job Search Only

**Prompt:**
```
Generate a reusable app that searches LinkedIn for contract roles matching my profile and writes a report. Search with keywords "Senior Software Architect .NET Azure", filter for UK, contract, senior level, remote. Score matches against my skills: C#, .NET Core, Azure, Python, AI/ML. Rate range £500-700/day. Exclude junior roles.
```

**Expected run params:**
- `keywords` (string or string[]) — search terms
- `outputFile` (string)

**Expected profile:**
- Skills, rate range, location, contract preference
- Exclusion rules
- Scoring criteria

**Expected constants:**
- LinkedIn API call pattern, scoring logic, report format

**What to watch for:** This is a subset of the job search prompt. Does the agent produce a proportionally simpler proposal, or does it balloon to the same complexity?

---

## Test 7: Simple One-Off — Should Skip Negotiation

**Prompt:**
```
Generate an app that lists my calendar events for today
```

**Expected behaviour:** Agent should skip the parameter/profile negotiation and generate directly. The directive says "for simple one-off prompts with no obvious parameters, skip this process."

**What to watch for:** Does the agent correctly identify this as a one-off with no reusable parameters? If it proposes params, that's over-engineering.

---

## Test 8: Explicit Skip

**Prompt:**
```
Just generate a job search app from job-search-prompt-v3.txt, don't ask me about parameters
```

**Expected behaviour:** Agent should skip negotiation and generate directly. The directive says "if the user says 'just generate it' or similar, skip negotiation."

**What to watch for:** Does the agent respect the explicit skip, or does it propose anyway?

---

## Test 9: Contacts Cleanup Report

**Prompt:**
```
Generate a reusable app that scans my Google Contacts and produces a cleanup-report.md identifying: contacts without email addresses, contacts without phone numbers, potential duplicates (similar names), and contacts not contacted in the last year. Group by category with counts.
```

**Expected run params:**
- `inactiveDays` (number, default 365) — threshold for inactive contacts
- `outputFile` (string, default "cleanup-report.md")

**Expected profile:** Minimal — possibly exclusion rules (VIPs to never flag).

**Expected constants:**
- Duplicate detection logic, report format, category structure

---

## Test 10: Cost Tracking Dashboard

**Prompt:**
```
Generate a reusable app that fetches my Anthropic API usage for a date range, breaks down costs by model, calculates daily averages, and writes a cost-report.md with a summary table and per-day breakdown. Use the anthropic-admin tools.
```

**Expected run params:**
- `startDate` (string) — start of date range
- `endDate` (string) — end of date range
- `outputFile` (string, default "cost-report.md")

**Expected profile:** Minimal — possibly per-model cost rates if not from the API.

**Expected constants:**
- Cost calculation logic, report format, table structure

---

## Test 11: Feedback Loop — Move Items Between Categories

Run Test 5 (research report) first, then test iterative feedback:

**Round 1:** Agent proposes params/profile/constants.
**Round 2:** "Move `days` to profile — I always want 7 days. Add `sources` as a run param with options 'web', 'github', or 'both'."
**Round 3:** "Actually, put `days` back as a run param. Looks good otherwise."

**What to watch for:**
- Does the agent re-present after each round of feedback?
- Does it track the cumulative changes correctly?
- Does it confirm and proceed to generation after the final approval?

---

## Test 12: Ambiguous — Could Go Either Way

**Prompt:**
```
Generate an app that monitors my Gmail for emails from a specific sender and forwards a summary to another email address whenever new ones arrive.
```

**Expected behaviour:** This prompt has parameters (sender, recipient) but is also sort of a one-off configuration. Does the agent propose, or generate directly? Either is defensible — the key is whether it makes a reasonable choice and explains its reasoning.

**Expected run params (if it proposes):**
- `sender` (string) — email to monitor
- `recipient` (string) — where to forward summaries

**Expected profile:** Minimal.

---

## Scoring

For each test, rate:

| Criterion | Pass | Fail |
|-----------|------|------|
| Proposed before generating (when expected) | Agent presented structured proposal | Went straight to `generate_code` |
| Correct format | Run params / Profile / Constants sections | Free-form prose, missing sections |
| Sensible split | Params = per-run, Profile = per-user, Constants = app logic | Everything in params, or everything hardcoded |
| Consistent across tests | Same structure as other tests | Different format, different detail level |
| Handles feedback | Re-presents updated proposal | Ignores feedback or loses changes |
| Skips when appropriate | Generates directly for simple/explicit-skip prompts | Proposes unnecessarily |
