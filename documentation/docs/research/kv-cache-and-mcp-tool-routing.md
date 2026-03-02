# KV Cache Mechanics and Implications for MCP Tool Routing

## Context

This document explores the feasibility of **smarter MCP tool routing** — sending only relevant tools to the LLM per turn instead of the full set. Understanding how Anthropic's prompt caching works at the infrastructure level (KV cache) is essential to evaluating the trade-offs.

Currently, all discovered MCP tools (~60-120) are sent to every API call. Prompt caching mitigates the cost. The question is whether selective tool routing (e.g., via a vector database) would be more efficient.

## How LLM Inference Works: Two Phases

### Phase 1 — Prefill

The model processes all input tokens to build the **KV cache**: key-value tensors for every attention head at every layer. This is the most GPU-intensive part of a request — a large matrix multiplication across all input tokens, all layers, all heads.

For a 100k-token input on a large model, this is significant compute time.

### Phase 2 — Decode (autoregressive generation)

The model generates output tokens one at a time. Each new token attends to the KV cache built during prefill. The KV cache is read, not recomputed, for previous tokens.

## What Is the KV Cache?

In a transformer, every token needs to "look at" every previous token to decide what's relevant. It does this through **attention**, which uses three vectors per token:

- **Q (Query):** "What am I looking for?"
- **K (Key):** "What do I contain?"
- **V (Value):** "What information do I provide?"

Attention works like a lookup: each token's Q is compared against every previous token's K to get relevance scores, then those scores weight the V vectors to produce the output.

### Why cache K and V?

When generating token N+1, the model needs the K and V vectors for all N previous tokens. But those vectors **don't change** — token 200's K and V are the same whether you're generating token 201 or token 5000.

Without caching, you'd recompute K and V for all previous tokens on every single output token — O(n^2) wasted work.

The KV cache stores every token's K and V after computing them once:

```
Generating token 501:
  - Load K_1..K_500 and V_1..V_500 from cache     <- memory read (cheap)
  - Compute K_501, V_501, Q_501 for the new token  <- one token of compute
  - Q_501 attends to all 501 K vectors
  - Weighted sum of all 501 V vectors -> output
  - Store K_501, V_501 into cache
```

### Size of the KV cache

The KV cache is per-layer, per-attention-head:

```
KV cache size ~ 2 x num_layers x num_heads x head_dim x sequence_length
```

For a large model with a 100k-token context, the KV cache can be **tens of gigabytes** of GPU memory. Expensive to store, but far cheaper than recomputing from scratch.

## Prompt Caching Across Providers

Normally the KV cache lives only for the duration of one request. Prompt caching **persists the KV cache across requests** server-side. Both Anthropic and OpenAI offer this, but with very different economics.

### Mechanics

The full prompt is still transmitted over the wire every time — caching is a **compute optimization, not a network optimization**. The provider detects that the request prefix matches a stored KV cache, skips the prefill computation for those tokens, and charges a reduced rate.

```
Request 1:  [system + tools + msg1]
            -> Full prefill computation for all tokens
            -> Store KV cache for the prefix (system + tools) server-side
            -> Cost: cache_creation_input_tokens at write premium (Anthropic only)

Request 2:  [system + tools + msg1 + response1 + msg2]
             |--- same prefix ---|
            -> Load cached KV for prefix (skip prefill for those tokens)
            -> Compute KV only for new tokens (msg1 + response1 + msg2)
            -> Cost: cache_read_input_tokens at discounted rate + fresh input at full rate
```

### Anthropic vs. OpenAI caching

| Aspect | Anthropic | OpenAI |
|--------|-----------|--------|
| Opt-in mechanism | Explicit `cache_control: {"type": "ephemeral"}` markers | Automatic (no markers needed) |
| Cache write premium | 1.25x input rate | None (no write surcharge) |
| Cache read discount | **90% off** (0.1x input rate) | **50-75% off** (varies by model) |
| TTL | ~5 minutes | ~5-10 minutes |
| Match type | Prefix-based, exact byte match | Prefix-based, exact byte match |

### Cache discount comparison by model

| Model | Input $/MTok | Cache Read $/MTok | Discount |
|-------|-------------|-------------------|----------|
| **Anthropic Haiku 4.5** | $1.00 | $0.10 | **90% off** |
| **Anthropic Sonnet 4.6** | $3.00 | $0.30 | **90% off** |
| **Anthropic Opus 4.6** | $5.00 | $0.50 | **90% off** |
| **OpenAI gpt-4.1** | $2.00 | $0.50 | **75% off** |
| **OpenAI gpt-4.1-mini** | $0.40 | $0.10 | **75% off** |
| **OpenAI gpt-4o** | $2.50 | $1.25 | **50% off** |
| **OpenAI gpt-4o-mini** | $0.15 | $0.075 | **50% off** |
| **OpenAI o4-mini** | $1.10 | $0.275 | **75% off** |

The difference is dramatic: Anthropic's cached tokens cost 10% of full price, while OpenAI's cost 25-50%. This fundamentally changes the routing calculus per provider.

### Cache match is prefix-based and exact

The cache hit depends on the **byte-level prefix** matching exactly. If you change which tools you send, their order, or any content before the cache boundary, the prefix changes and the cache misses. With Anthropic, a miss means paying the cache-creation surcharge (1.25x) again. With OpenAI, there's no write penalty but you lose the read discount.

## Implications for MCP Tool Routing

### Real-world example: OpenAI tool schema overhead

A real 3-call session using OpenAI with 61 MCP tools demonstrated the problem:

```
Call 1:  input_tokens=6,884   tool_schema_count=61  output_tokens=21
Call 2:  input_tokens=8,238   tool_schema_count=61  output_tokens=1,171
Call 3:  input_tokens=9,543   tool_schema_count=61  output_tokens=92
```

The agent did trivial work (read a file, call codegen, summarize) producing ~1,300 output tokens total, but paid for **~25K input tokens** because the 61 tool schemas (~5-6K tokens) were sent with every call. OpenAI's caching helped (22K `cache_read` tokens), but at only a 50-75% discount those cached tokens were still expensive.

With Anthropic's 90% cache discount, the same cached tokens would cost 2-5x less. This is why the choice of provider fundamentally changes the routing decision.

### Current approach: send all tools, rely on caching

Assuming ~12,700 tokens of system prompt + tool schemas (from real Anthropic session data) and a 10-turn session:

**With Anthropic (90% cache discount):**
- Turn 1 cache write: `12,700 * $1.25/MTok = $0.016`
- Turns 2-10 cache read: `12,700 * $0.10/MTok * 9 = $0.011`
- **Total for cached prefix: $0.027**

**With OpenAI gpt-4.1 (75% cache discount):**
- Turn 1 (no write premium): `12,700 * $2.00/MTok = $0.025`
- Turns 2-10 cache read: `12,700 * $0.50/MTok * 9 = $0.057`
- **Total for cached prefix: $0.082** (3x Anthropic)

**With OpenAI gpt-4o (50% cache discount):**
- Turn 1: `12,700 * $2.50/MTok = $0.032`
- Turns 2-10 cache read: `12,700 * $1.25/MTok * 9 = $0.143`
- **Total for cached prefix: $0.175** (6.5x Anthropic)

### Vector DB routing: send only relevant tools

If routing reduces the tool set from ~60 to ~15 tools per turn (~3,200 tokens):

**Anthropic (best case, stable tool set):**
- Turn 1 cache write: `3,200 * $1.25/MTok = $0.004`
- Turns 2-10 cache read: `3,200 * $0.10/MTok * 9 = $0.003`
- Total: $0.007 — **saves $0.020 vs. all-tools** (modest)

**Anthropic (worst case, tool set changes every turn):**
- Cache write every turn: `3,200 * $1.25/MTok * 10 = $0.040`
- **Costs $0.013 MORE than all-tools with caching**

**OpenAI gpt-4.1 (best case, stable tool set):**
- Turn 1: `3,200 * $2.00/MTok = $0.006`
- Turns 2-10 cache read: `3,200 * $0.50/MTok * 9 = $0.014`
- Total: $0.020 — **saves $0.062 vs. all-tools** (significant)

**OpenAI gpt-4.1 (worst case, tool set changes every turn):**
- Full input every turn: `3,200 * $2.00/MTok * 10 = $0.064`
- **Still saves $0.018 vs. all-tools with caching** — routing wins even with zero cache hits

**OpenAI gpt-4o (best case, stable tool set):**
- Turn 1: `3,200 * $2.50/MTok = $0.008`
- Turns 2-10 cache read: `3,200 * $1.25/MTok * 9 = $0.036`
- Total: $0.044 — **saves $0.131 vs. all-tools** (dramatic)

### Summary: routing savings by provider

| Provider | All tools (cached) | Routing (best) | Routing (worst) | Routing saves? |
|----------|-------------------|----------------|-----------------|----------------|
| Anthropic Haiku | $0.027 | $0.007 | $0.040 | Only if stable |
| OpenAI gpt-4.1 | $0.082 | $0.020 | $0.064 | **Always** |
| OpenAI gpt-4o | $0.175 | $0.044 | $0.100 | **Always** |

**Key insight:** With Anthropic's 90% cache discount, routing only wins when the tool set is stable across turns. With OpenAI's weaker discounts (50-75%), routing wins even in the worst case — sending fewer tools always saves money because cached tokens are still expensive.

### Additional costs of routing

Vector DB routing introduces overhead not present in the current approach:

| Cost | Impact |
|------|--------|
| Embedding model API call per turn | ~$0.0001 per query (small, but adds up) |
| Vector DB memory/storage | Negligible for ~100 tools |
| False negatives (relevant tool excluded) | **Correctness risk** — the LLM can't use a tool it doesn't know about |
| Dependency complexity | New runtime dependency (embedding model, vector store) |
| Latency per turn | Extra ~50-100ms for embedding + similarity search |

These overheads are small compared to the potential savings, especially on OpenAI where routing saves $0.06-0.13 per 10-turn session even in adverse conditions.

### When routing wins vs. caching

| Scenario | Anthropic | OpenAI |
|----------|-----------|--------|
| Multi-turn, stable tool needs | Caching wins | Routing wins |
| Multi-turn, varying tool needs | Break-even | Routing wins |
| Single-turn / stateless | Routing wins | Routing wins |
| Very large tool sets (200+) | Routing wins | Routing wins |
| Small tool sets (<20) | Caching wins | Caching wins |

### The false-negative problem

The most dangerous risk of tool routing is **excluding the right tool**. If the vector search returns the top-15 tools but the user's intent requires tool #16, the LLM has no way to recover — it doesn't know the tool exists. This is a correctness failure, not just a cost issue.

Mitigations:
- **Always-include list** — high-frequency tools (filesystem, bash) bypass routing
- **Higher k** — retrieve top-30 instead of top-15, reducing false negatives but also reducing savings
- **Two-phase selection** — LLM first sees tool names only (cheap), selects which it needs, then full schemas are sent

## Alternative Approaches

### Static tool groups (no vector DB)

Configure tool groups in config.json tied to task types:

```json
{
  "ToolGroups": {
    "coding": ["filesystem", "codegen", "github"],
    "research": ["web", "google", "linkedin"],
    "communication": ["whatsapp", "google"]
  }
}
```

The user or system prompt selects a group. Simple, deterministic, no false-negative risk within the group. No embedding dependency.

**Trade-off:** Requires manual curation. Doesn't adapt to novel tasks.

### LRU / recency-based filtering

After the first turn, preferentially include tools the agent has already used in this session, plus a discovery set of unused tools.

**Trade-off:** Doesn't help on turn 1. Biases toward tools already used rather than tools needed next.

### Two-phase tool selection

Turn 1 sends only tool names and one-line descriptions (small token footprint). The LLM responds with which tools it wants. Turn 2 sends full schemas for selected tools only.

**Trade-off:** Adds an extra API round-trip per turn. The name+description list itself may be small enough that the savings don't justify the latency.

## Conclusion

The routing decision is **provider-dependent**, not one-size-fits-all:

**Anthropic (90% cache discount):** At the current scale (~60-100 tools, multi-turn conversations), prompt caching is likely more cost-effective than routing. The cached prefix costs ~$0.001/turn after the first, and there's zero risk of excluding the right tool. Routing only makes sense at 200+ tools or single-turn scenarios.

**OpenAI (50-75% cache discount):** Routing wins at the current scale. Even with perfect cache hits, OpenAI's weak discount means cached tool schemas remain a significant cost. The real-world example (61 tools, 3 calls, trivial work) demonstrated this — most of the cost was tool schema overhead despite caching. Routing from 60 to 15 tools saves $0.06-0.13 per 10-turn session, even in worst-case cache-miss scenarios.

### Recommended approach

For a **multi-provider agent** that supports both Anthropic and OpenAI:

1. **Start with static tool groups** — simplest implementation, no new dependencies, works well when task types are predictable. Configure in `config.json`, select per session.
2. **If groups prove too rigid, add vector similarity routing** — embed tool descriptions at startup, query per turn with user message, return top-k. Use an always-include list for high-frequency tools (filesystem, bash).
3. **Make routing provider-aware** — more aggressive filtering for OpenAI (top-15), less aggressive for Anthropic (top-30 or off entirely), since the cost/benefit ratio differs dramatically.
4. **Use higher k values** to minimize false negatives, accepting reduced savings. Correctness matters more than cost optimization.

## Related

- [Prompt Caching Cost Analysis](../operations/prompt-caching-cost-analysis.md) — real session cost data with/without caching
- [ADR-012: Layered Cost Reduction](../architecture/decisions/ADR-012-layered-cost-reduction.md) — prompt caching is Layer 1
- [DESIGN: Tool System](../design/DESIGN-tool-system.md) — tool discovery and MCP architecture
