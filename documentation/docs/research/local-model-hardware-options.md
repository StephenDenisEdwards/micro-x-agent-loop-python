# Local Model Inference: Hardware Options & Findings

Research into running local LLM models for semantic routing, with a focus on cost-effective hardware for tool-calling workloads.

**Date:** March 2026
**Context:** Testing semantic model routing with local Ollama models via `config-testing-semantic-routing-local-*.json` configurations.

---

## Current Hardware Baseline

| Component | Spec |
|-----------|------|
| GPU | NVIDIA GeForce RTX 3050 Ti Laptop GPU |
| VRAM | 4 GB |
| Platform | Windows 11, laptop (no expansion slots) |
| Max model size | ~7b (Q4 quantization) |

---

## Model Size vs VRAM Requirements

| Model Size | VRAM (Q4) | VRAM (Q8) | Example Models |
|------------|-----------|-----------|----------------|
| 3b | 2-3 GB | 4-5 GB | phi-3.5-mini, qwen2.5:3b |
| 7b | 4-5 GB | 7-8 GB | qwen2.5:7b, llama-3.1:7b, mistral:7b |
| 14b | 8-10 GB | 14-16 GB | qwen2.5:14b |
| 32b | 18-22 GB | 32-36 GB | qwen2.5:32b |
| 70b | 38-44 GB | 70-80 GB | llama-3.1:70b, qwen2.5:72b |

---

## Experimental Findings: qwen2.5:7b on 4GB VRAM

### What works

- **Trivial/conversational tasks** — greetings, simple questions, short factual answers
- **tool_search discovery** — calling the `tool_search` pseudo-tool with keyword queries
- **Processing tool results** — formatting and summarizing returned data
- **pin_continuation** — keeps the model consistent within a multi-iteration turn
- **Compact system prompt** — reduces system prompt overhead for small context windows
- **tool_search_only** — narrows tool schemas to 2 (tool_search + ask_user), reducing confusion

### What doesn't work reliably

- **Structured tool calling with unfamiliar schemas** — the 7b model guesses parameters instead of reading the tool schema. For example, it omits required parameters (`query` on `gmail_search`) or passes incorrect parameter names.
- **Multi-turn tool sessions** — after the first turn with tool use, subsequent turns degrade. The model sees old tool_use/tool_result in the message history but struggles to construct new correct tool calls. Starting a fresh session (`/session new`) before each prompt works around this.
- **Complex parameter construction** — even when the model discovers the right tool via tool_search, it often fails to construct the correct invocation from the schema alone.

### Performance characteristics (qwen2.5:7b on RTX 3050 Ti)

| Metric | Typical Range |
|--------|---------------|
| Time to first token | 0.7–9.1 seconds |
| Total turn duration | 3–54 seconds |
| Context sensitivity | Degrades noticeably with >10 messages |
| Tool call accuracy | Reliable for tool_search; unreliable for MCP tools with complex schemas |
| Cost | $0.00 (local inference) |

### Root cause analysis

The 7b model lacks sufficient reasoning capacity to:
1. Parse JSON tool schemas and map user intent to correct parameters
2. Distinguish between required and optional parameters
3. Maintain tool-calling accuracy as conversation context grows

This is a fundamental model capability limitation, not a routing or configuration bug.

---

## Hardware Upgrade Options

### Dedicated Local Hardware

| Option | Memory | Runs | Cost | Notes |
|--------|--------|------|------|-------|
| **RTX 4060 Ti 16GB** (desktop GPU) | 16 GB VRAM | 14b | ~$400-450 | Requires desktop PC |
| **RTX 3090 24GB** (used, desktop) | 24 GB VRAM | 32b | ~$700 | Best value per GB; requires desktop PC with adequate PSU |
| **RTX 4090 24GB** (desktop) | 24 GB VRAM | 32b | ~$1,600 | Faster inference than 3090 |
| **Mac Mini M4 Pro 48GB** | 48 GB unified | 32b comfortably | ~$2,000 | Silent, low power (~20W idle), runs as network Ollama server |
| **MacBook Pro M3/M4 Pro 36GB** | 36 GB unified | 14b–32b | ~$2,000-2,500 | Portable, shared memory works well with Ollama |
| **MacBook Pro M3/M4 Max 64GB** | 64 GB unified | 32b–70b | ~$3,000-4,000 | Sweet spot for serious local LLM work |
| **Mac Studio M2 Ultra 192GB** | 192 GB unified | 70b+ | ~$4,000+ | Overkill but future-proof |

**Recommendation for a laptop user:** A **Mac Mini M4 Pro 48GB (~$2,000)** as a dedicated network Ollama server is the best option. It sits on the desk, the agent config points at `http://mac-mini:11434`, and it runs 32b models with reliable tool calling. Low power, silent, tiny footprint.

### Cloud GPU Options

#### Vast.ai (On-Demand) — Best for experimentation

Marketplace model where hosts set prices; rates fluctuate with supply/demand.

| GPU | VRAM | Typical $/hr | Runs | Notes |
|-----|------|-------------|------|-------|
| **RTX 3090** | 24 GB | **$0.15–0.30** | 32b | Best value for testing |
| RTX 4090 | 24 GB | $0.30–0.50 | 32b | Faster inference |
| A40 | 48 GB | $0.40–0.60 | 70b | Larger models |
| A100 | 80 GB | $0.80–1.20 | 70b+ | Production-grade |

**How it works:**
- Per-second billing, no minimum hours, no lock-in
- Full machine access — install Ollama, pull models, expose port
- **On-demand**: guaranteed uptime, standard pricing
- **Interruptible**: 50%+ cheaper, but machine can be reclaimed (good for batch/testing)
- No cold start — machine is yours until you stop it
- 40+ data centers, 68+ GPU types available

**Typical experimentation session:** Spin up RTX 3090, install Ollama, pull qwen2.5:32b, test for a few hours, shut down. Total cost: ~$1–2.

#### RunPod — Pods (On-Demand) and Serverless

**RunPod Pods** (on-demand machines, like Vast.ai):

| GPU | VRAM | $/hr | Runs |
|-----|------|------|------|
| **L4/A5000/3090** | 24 GB | **~$0.44** | 32b |
| 4090 PRO | 24 GB | ~$0.69 | 32b |
| A6000/A40 | 48 GB | ~$0.76 | 70b |
| A100 | 80 GB | ~$1.64 | 70b+ |

**RunPod Serverless** (auto-scaling, pay-per-request):

| GPU | VRAM | Flex $/hr | Active $/hr |
|-----|------|-----------|-------------|
| L4/A5000/3090 | 24 GB | $0.68 | $0.47 |
| A6000/A40 | 48 GB | $1.22 | $0.86 |
| 4090 PRO | 24 GB | $1.12 | $0.76 |
| A100 | 80 GB | $2.74 | $2.16 |
| H100 PRO | 80 GB | $4.18 | $3.35 |

**Serverless billing:**
- Flex workers scale to zero when idle — pay only when processing
- Per-second billing from worker start to stop
- Workers stay alive ~5 seconds after request completion (configurable)
- Cold start: sub-200ms with FlashBoot for cached containers; 6–12s for large models (50GB+)
- Storage: ~$0.10/GB/month for container image, $0.05–0.07/GB/month for network volumes
- Default spend limit: $80/hour

**Serverless caveat for Ollama:** Serverless is designed for stateless request/response (vLLM/TGI templates), not a persistent Ollama server. Cold starts loading a 32b model would be slow. **RunPod Pods are a better fit** for interactive Ollama experimentation.

---

## Cost Comparison: Local vs Cloud vs API

Assuming interactive use (~4 hours/day, ~20 days/month = 80 hours/month):

| Option | Monthly Cost | Setup Cost | Tool Calling Reliability |
|--------|-------------|------------|--------------------------|
| **qwen2.5:7b on RTX 3050 Ti** | $0 (electricity) | $0 (existing) | Poor for complex tools |
| **Vast.ai RTX 3090 (qwen2.5:32b)** | ~$16–24 | $0 | Good |
| **RunPod Pod 3090 (qwen2.5:32b)** | ~$35 | $0 | Good |
| **Mac Mini M4 Pro (qwen2.5:32b)** | ~$5 (electricity) | ~$2,000 | Good |
| **Claude Haiku API** | ~$5–15 (at typical usage) | $0 | Excellent |
| **Claude Sonnet API** | ~$50–150 (at typical usage) | $0 | Excellent |

**Key insight:** For tool-calling tasks specifically, Claude Haiku at $0.80/$4.00 per MTok is often cheaper than renting a cloud GPU, with significantly better tool-calling reliability. Local models make more economic sense for high-volume, simple tasks (trivial/conversational routing) where the cost is $0.

---

## Integration with Semantic Routing

The semantic routing system (`RoutingPolicies` in config) allows mixing local and cloud models:

```json
{
  "RoutingPolicies": {
    "trivial":         { "provider": "ollama", "model": "qwen2.5:7b" },
    "conversational":  { "provider": "ollama", "model": "qwen2.5:7b" },
    "factual_lookup":  { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "summarization":   { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "code_generation": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
    "tool_continuation": { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" }
  }
}
```

This hybrid approach routes cheap tasks locally and tool-heavy or complex tasks to API models, optimizing for both cost and reliability.

### Potential improvement: iteration-based escalation

A possible enhancement is automatic escalation from local to API models when tool calling fails repeatedly within a turn (e.g., after N failed iterations, switch to Haiku). This would let the system attempt local inference first and fall back gracefully.

---

## References

- [RunPod Serverless Pricing](https://docs.runpod.io/serverless/pricing)
- [RunPod Pricing Overview](https://www.runpod.io/pricing)
- [Vast.ai Pricing](https://vast.ai/pricing)
- [Top Serverless GPU Clouds for 2026](https://www.runpod.io/articles/guides/top-serverless-gpu-clouds)
- [GPU Price Comparison 2026](https://getdeploying.com/gpus)
- [Where to Buy or Rent GPUs for LLM Inference (2026)](https://www.bentoml.com/blog/where-to-buy-or-rent-gpus-for-llm-inference)
