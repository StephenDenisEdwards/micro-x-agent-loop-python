# Claude Agent vs. Console App - Comparison

## Overview

Both approaches search for jobs, score them, and generate reports. This document explains the differences and when to use each.

## Claude Agent (Original Approach)

### How It Works

```
User asks Claude → Claude agent uses tools → Claude scores jobs → Claude generates report
```

### Tools Used

- `google__gmail_search` - Search Gmail
- `google__gmail_read` - Read email content
- `linkedin__linkedin_jobs` - Search LinkedIn
- `linkedin__linkedin_job_detail` - Get job details
- `filesystem__write_file` - Write output
- `filesystem__append_file` - Append to output

### Cost Structure

| Operation | Cost |
|-----------|------|
| Gmail search (1) | ~$0.03 per 1M tokens (cheap) |
| Email read (1-50 jobs) | Input ~$0.15 (email body text) |
| LinkedIn search (1) | ~$0.03 per 1M tokens (cheap) |
| Job detail fetch (1-30 jobs) | Input ~$0.30-$1.00 (spec text) |
| Scoring (Claude decides) | **~$1-2 per job** (expensive) |
| Report generation | Input ~$0.20, Output ~$0.50 |
| **Total per run** | **~$3-5 USD** |

### Pros

✓ Natural language scoring (understands nuance)  
✓ Explainable decisions (Claude explains why)  
✓ Flexible scoring (easy to adjust on-the-fly)  
✓ Smart summaries (Claude writes good text)  
✓ One-command execution  

### Cons

✗ Expensive ($3-5 per run × 1-7 runs/week = $15-35/month)  
✗ Slow (10-30 seconds per run due to API latency)  
✗ Not reproducible (same input may yield different scores)  
✗ Requires API key management  
✗ Requires internet connection  
✗ Rate limits apply  

## Console App (This Implementation)

### How It Works

```
User runs app → App uses MCP → App scores jobs → App generates report
```

### Components Used

| Component | Cost |
|-----------|------|
| Gmail API (via MCP) | Free (your own credentials) |
| LinkedIn API (via MCP) | Free (your own credentials) |
| Scoring (heuristic rules) | **$0** (no LLM) |
| Report generation | $0 (template-based) |
| **Total per run** | **$0** |

### Pros

✓ **Zero LLM costs** ($0 per run)  
✓ **Fast** (<5 seconds per run)  
✓ **Deterministic** (same input = same score)  
✓ **Transparent** (clear heuristic rules)  
✓ **Scriptable** (integrate into cron/automation)  
✓ **Works offline** (no internet after initial fetch)  
✓ **Extensible** (easy to adjust weights)  

### Cons

✗ More setup (requires MCP servers)  
✗ Less intelligent (heuristic rules, not LLM)  
✗ Requires understanding of scoring algorithm  
✗ May miss subtle job fit factors  

## Cost Comparison (Monthly)

### Claude Agent Scenario
- Run 2x per week (weekday job searches)
- $4 per run × 8 runs = **$32/month**
- Plus API key, error handling, occasional re-runs

### Console App Scenario
- Run daily (automated)
- $0 per run × 30 runs = **$0/month**
- One-time MCP server setup cost (if not already available)

### Annual Savings

| Usage Pattern | Agent Cost | App Cost | Savings |
|---------------|-----------|---------|---------|
| 2x/week | $384/year | $0/year | **$384** |
| Daily | $1,460/year | $0/year | **$1,460** |
| Multiple users | $384 × N | $0 × N | **$384N** |

## Scoring Comparison

### Claude Agent Scoring

```
User provides job spec → Claude reads full spec → Claude evaluates against criteria
→ Claude outputs score 1-10 with explanation

Example: "This is a strong match (8/10) because it has .NET, Azure, and microservices
(all core to the role) at £550/day (within range), though location is hybrid not remote..."
```

**Advantages:**
- Understands context and nuance
- Explains reasoning
- Can adjust for trade-offs dynamically

**Disadvantages:**
- Takes 3-5 seconds per job
- Expensive (LLM tokens)
- May be inconsistent across jobs

### Console App Scoring

```
Job text → Regex extraction → Heuristic scoring

Example:
- Technology: .NET, Azure, Microservices = 3 matches → 8/10
- Seniority: "Senior Architect" → 10/10
- Rate: £550/day → 8/10
- Sector: Healthcare → 7/10
- Location: Remote UK → 10/10
- Bonuses: None → +0
- Weighted total: 0.30×8 + 0.25×10 + 0.20×8 + 0.15×7 + 0.10×10 = 8.3/10
```

**Advantages:**
- Instant (<1ms per job)
- Transparent (see exact calculation)
- Reproducible (always same result)
- Cheap (no API costs)

**Disadvantages:**
- Misses context (keyword-based only)
- No explanation (just a number)
- Fixed weights (not dynamic)

## Example Job Scoring

### Job: "Senior .NET Architect - Healthcare - London - £550/day - 6 months - Outside IR35"

**Claude Agent:**
```
Score: 8/10

Reasoning: Strong match. Senior architect role with core .NET/Azure stack, 
great rate (£550/day), preferred healthcare sector, London location, and 
outside IR35 status. Only downside: 6 months is toward short end of preferred 
3-12 month range, but still acceptable for high-quality role.

Recommendation: Apply immediately.
```
(Takes 3-5 seconds, costs ~$0.10)

**Console App:**
```
Technology: .NET, Azure, Microservices, Architecture = 4 matches → 10/10
Seniority: "Senior Architect" → 10/10
Rate: £550/day → 8/10
Sector: Healthcare → 10/10
Location: London → 10/10
Bonuses: Outside IR35 (+0.5), Architecture (+0.3) = +0.8
Final: 0.30×10 + 0.25×10 + 0.20×8 + 0.15×10 + 0.10×10 + 0.8 = 9.3/10
```
(Takes <1ms, costs $0)

**Both reach similar conclusion but via different routes.**

## When to Use Each

### Use Claude Agent When:

1. **Uncertain scoring criteria** - Let Claude figure out best heuristics
2. **Complex trade-offs** - Need LLM judgment on context
3. **One-off analysis** - Don't need to minimize cost
4. **Natural language needed** - Want human-readable explanations
5. **Ad-hoc exploration** - Quick investigation rather than routine

### Use Console App When:

1. **Regular automation** - Running daily or multiple times/week
2. **Cost-sensitive** - Budget constraints
3. **Consistent rules** - Want reproducible, predictable scoring
4. **Speed required** - Need instant results
5. **Scale** - Running for multiple people
6. **Offline operation** - No reliable internet

## Hybrid Approach

Could combine both:

```
Weekdays: Run console app (routine, cost-effective)
Weekends: Run Claude agent for one-off opportunities (flexibility, intelligence)
```

Or:

```
Console app generates initial report
Claude agent reviews top 5 for deeper analysis
```

## Migration Path

If currently using Claude agent and want to switch to console app:

1. **Week 1**: Install and test console app with dry run
2. **Week 2**: Set up MCP servers for Gmail/LinkedIn
3. **Week 3**: Run console app in parallel with Claude agent
4. **Week 4**: Switch to console app, retire Claude agent flow
5. **Ongoing**: Monitor and adjust scoring weights based on outcomes

## Conclusion

| Factor | Agent | App |
|--------|-------|-----|
| Cost | $$$ | Free |
| Speed | Slow | Fast |
| Intelligence | High | Medium |
| Reproducibility | Low | High |
| Transparency | Medium | High |
| Setup | Easy | Medium |
| Automation | Hard | Easy |

**Recommendation:** Use **console app for routine job searching** (save costs, gain speed), fall back to **Claude agent for special cases** (complex trades, strategic decisions).
