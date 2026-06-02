# Observability for AI Agents

A "do this in production" guide to making AI agents inspectable, debuggable, and cost-controllable.

## What it is

Observability for AI agents is the practice of capturing enough signal from a running agent — across LLM calls, tool invocations, memory operations, and control flow — to **reconstruct what it did, why it did it, and what it cost**, after the fact and in real time. It borrows from traditional software observability (logs, metrics, traces) but adapts to the non-deterministic, multi-step, multi-actor nature of agents.

The three classic pillars, mapped to agents:

| Pillar | In normal software | In agents |
|---|---|---|
| **Logs** | Stdout, errors | Prompts, completions, tool I/O, system events |
| **Metrics** | Latency, error rate, QPS | Tokens, cost, tool latency, turn count, success rate, cache hit rate |
| **Traces** | Distributed request graph | Turn → LLM call → tool calls → sub-agents → memory ops |

Plus a fourth pillar unique to agents:

- **Evals & feedback** — scoring whether an output was actually correct/useful (since "200 OK" doesn't mean the answer was right).

## Why it matters

1. **Non-determinism.** Same prompt, different output. Without traces you can't reproduce or debug failures.
2. **Cost is a first-class concern.** A bug isn't just "wrong answer" — it can be a runaway loop burning $50 of Opus tokens per session. You need cost per turn, per session, per user.
3. **Long causal chains.** Agents chain LLM → tool → LLM → sub-agent. A wrong final answer might originate 8 steps upstream. Traces are the only way to find the root cause.
4. **Silent failures.** A tool returning malformed JSON, a truncated context, a cache miss, a mode misclassification — none of these throw errors but all degrade behaviour.
5. **Drift.** Model providers update models; prompts that worked yesterday regress today. You only catch this if you're measuring quality continuously.
6. **Safety & compliance.** Audit trail of what the agent saw, said, and did — required for regulated domains and for incident response.
7. **Optimisation.** You can't reduce latency or cost you can't see. Cache hit rate, routing decisions, tool retry counts — all need instrumentation.

## Best practices

### Instrument at the right granularity

- One trace per **session**, spans per **turn**, child spans per **LLM call / tool call / sub-agent / memory op**.
- Attach token counts, cost, model, cache hits, latency, and retry count to every LLM span.
- Attach input/output sizes, success/failure, and duration to every tool span.

### Capture inputs and outputs verbatim — but think about PII

- Store prompts and completions so failures are reproducible.
- Redact secrets and PII at the sink, not at the source — you want raw data available for debugging under access control.

### Make cost a metric, not an afterthought

- Track `$ per session`, `$ per task type`, `$ per user`. Alert on outliers.
- Break down by model so routing decisions are visible (e.g. "Haiku handled 70% of turns at 5% of cost").

### Use structured events, not free-text logs

- JSON events with stable schemas. Future-you (and your eval pipeline) will need to query them.

### Close the loop with evals

- **Offline:** golden datasets + LLM-as-judge or human review on regressions.
- **Online:** thumbs-up/down, task-completion signals, downstream conversion. Pipe these back to traces so you can ask "what did failed sessions have in common?"

### Alert on agent-shaped failure modes

- Turn count exceeding budget (infinite-loop guard).
- Tool error rate spikes.
- Cost-per-session p99 drift.
- Classifier confidence dropping (model drift signal).
- Cache hit rate falling (prompt churn signal).

### Sample intelligently

- 100% trace capture for errors and high-cost sessions; sample the rest. Traces aren't free.

### Tie traces to identity and version

- Tag every trace with model version, prompt version, config hash, code SHA. When you change something, you want to A/B before/after.

### Privacy by design

- Encrypt prompts/completions at rest. Time-bound retention. Access logs on the observability store itself.

## Tooling landscape

- **OpenTelemetry** — emerging standard; the GenAI semantic conventions define span names and attributes for LLM calls.
- **LLM-native platforms** — Langfuse, LangSmith, Helicone, Arize Phoenix, Braintrust, W&B Weave. All offer traces + evals + cost tracking, varying on self-hosted vs SaaS.
- **General APM** — Datadog, Honeycomb, Grafana now have LLM-aware views layered on OTel.
- **Roll-your-own** — SQLite + structured events works fine at small scale (this project's `memory.db` + `events` table is a minimal version of this).

## How this project handles it today

`micro-x-agent-loop-python` already implements several of these patterns:

| Practice | Where it lives |
|---|---|
| Structured event emission | `metrics.py` (event builders, `SessionAccumulator`) |
| Per-session cost tracking | `metrics.py` + `/cost` command |
| Session/message/tool-call persistence | `memory/` SQLite store (sessions, messages, tool_calls, events tables) |
| Routing outcome recording | `routing_feedback.py` (SQLite-backed) |
| Checkpoint/rewind for debugging | `memory/` checkpoint tables, `services/checkpoint_service.py` |
| Cost-aware routing | `provider_pool.py`, `task_taxonomy.py`, `RoutingPolicies` config |

### Gaps that would round out the story

- **OTel exporter** — emit GenAI-conventional spans so traces can land in any APM.
- **Online evals harness** — scheduled scoring of recent sessions against a rubric.
- **Alerting** — turn/cost/cache-hit thresholds piped to a notifier (Slack, email).
- **Per-user / per-task cost rollups** — currently per-session; the data is there but not aggregated.

## References

- OpenTelemetry GenAI semantic conventions: <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- Related project docs:
  - [Cost Metrics Design](../design/DESIGN-cost-metrics.md)
  - [Memory System Design](../design/DESIGN-memory-system.md)
  - [Metrics and Costs](../operations/metrics-and-costs.md)
  - [Session Memory Schema](../guides/session-memory-schema.md)
