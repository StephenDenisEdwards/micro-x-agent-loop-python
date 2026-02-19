# Agent Prompt Examples

Reusable prompts for common workflows in `micro-x-agent-loop-python`.

## General Productivity

```text
Summarize my unread recruiter emails from the last 3 days and propose 5 follow-up replies in draft form.
```

```text
Search my calendar for this week and create a 30-minute prep block before each interview event.
```

## Job Search

```text
Execute the job search prompt from documentation/docs/examples/job-search-prompt.txt.
```

```text
Run documentation/docs/examples/job-search-prompt.txt but only include roles scoring 7+/10 and paying £600+/day.
```

## Voice / STT Mode

```text
/voice start microphone
```

```text
/voice start microphone --mic-device-name "Headset (Jabra Evolve2 65)" --chunk-seconds 2 --endpointing-ms 500 --utterance-end-ms 1500
```

```text
When voice mode is active, treat each finalized utterance as a normal user turn and keep responses concise.
```

```text
/voice status
```

```text
/voice events 50
```

```text
/voice stop
```

## Interview Assist MCP

```text
Run interview-assist__ia_healthcheck and tell me exactly what is missing if any checks fail.
```

```text
Evaluate this session with interview-assist__ia_evaluate_session and summarize precision, recall, F1, and key false-positive patterns.
```

```text
Start a continuous transcription session from microphone, poll updates, and show only finalized utterances.
```

## WhatsApp MCP

```text
Find my last chat with John, summarize the previous 20 messages, and draft a reply confirming availability tomorrow afternoon.
```

```text
Send this message to Alice on WhatsApp: "Running 10 minutes late, will call when I arrive."
```

## GitHub MCP

```text
List my open PRs in StephenDenisEdwards/micro-x-agent-loop-python and flag any with merge conflicts or missing reviewers.
```

```text
Create a GitHub issue in StephenDenisEdwards/micro-x-agent-loop-python titled "Improve voice mode latency metrics" with a short implementation checklist.
```
