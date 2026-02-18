# Example Prompts

This directory contains example prompt files that demonstrate how to use the agent loop for real-world tasks. These are working prompts designed for the tools available in this project (Gmail, LinkedIn, Calendar, file I/O).

## Job Search

A multi-tool workflow that searches Gmail (JobServe alerts) and LinkedIn for contract roles, scores them against configurable criteria, and produces a ranked markdown report.

### Files

| File | Purpose |
|------|---------|
| `job-search-prompt.txt` | Main prompt with scoring criteria and report format template. Place alongside a `job-search-criteria.txt` with your personal preferences. |
| `job-search-prompt-variants.txt` | Alternative prompts (quick, weekly, high-value, remote-only), customization snippets (filters, highlights, enhancements), and usage instructions. |

### How it works

1. The agent reads `job-search-criteria.txt` for personal skill/rate/location preferences
2. Searches Gmail for JobServe alert emails from the last 24 hours
3. Searches LinkedIn for matching UK contract roles
4. Scores each job 1-10 against the criteria (tech match, seniority, rate, sector, location, IR35)
5. Writes a structured markdown report (`todays-jobs-YYYY-MM-DD.md`) with:
   - Top 10 ranked summary with anchor links
   - Full JobServe listings with scores and reasoning
   - Full LinkedIn listings with scores and reasoning
   - Summary statistics (technology counts, sectors, location distribution, market observations)

### Tools used

- `gmail_search` / `gmail_read` — retrieve JobServe alert emails
- `linkedin_jobs` — search for matching roles
- `linkedin_job_detail` — get full job descriptions for scoring
- `write_file` / `append_file` — produce the output report in stages
