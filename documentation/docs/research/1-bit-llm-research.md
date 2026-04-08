# 1-Bit LLMs: Technical Research & Implications for Cost-Aware Agent Systems

**Date:** April 2026
**Context:** Investigating ultra-low-bit quantization for LLM inference — what's real, what's hype, and how it applies to multi-tier agent architectures with cost-aware model routing.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What "1-Bit" Actually Means](#2-what-1-bit-actually-means)
3. [Key Research: Microsoft BitNet Family](#3-key-research-microsoft-bitnet-family)
4. [Key Research: PrismML Bonsai](#4-key-research-prismml-bonsai)
5. [Other 1-Bit / Ultra-Low-Bit Research](#5-other-1-bit--ultra-low-bit-research)
6. [Training Techniques for 1-Bit Models](#6-training-techniques-for-1-bit-models)
7. [Theoretical Foundations](#7-theoretical-foundations)
8. [Practical Tooling & Inference Engines](#8-practical-tooling--inference-engines)
9. [llama.cpp Extreme Quantization Ecosystem](#9-llamacpp-extreme-quantization-ecosystem)
10. [Hardware for 1-Bit Inference](#10-hardware-for-1-bit-inference)
11. [Domain-Specific Results](#11-domain-specific-results)
12. [Speculative Decoding with 1-Bit Draft Models](#12-speculative-decoding-with-1-bit-draft-models)
13. [Competing Approaches: Pruning, Distillation, MoE](#13-competing-approaches-pruning-distillation-moe)
14. [Energy & Sustainability Impact](#14-energy--sustainability-impact)
15. [Real-World Deployment Status](#15-real-world-deployment-status)
16. [Implications for This Project](#16-implications-for-this-project)
17. [Timeline & Maturity Assessment](#17-timeline--maturity-assessment)
18. [References](#18-references)

---

## 1. Overview

The core idea behind 1-bit LLMs: neural network weights can be compressed to ~1.58 bits (ternary: {-1, 0, +1}) with surprisingly little quality loss, dramatically reducing memory footprint, bandwidth requirements, and energy consumption.

### Why this matters

The real bottleneck in LLM inference is **memory bandwidth, not compute**. Moving weights from memory to processing units dominates both latency and energy. Reducing weight precision from 16 bits to ~1.58 bits cuts memory traffic by ~10x, fundamentally changing the inference cost equation.

### Key claims vs reality

| Claim | Verdict | Detail |
|-------|---------|--------|
| 10-20x memory reduction | **Confirmed** | BitNet 2B: 0.4 GB vs 2.0-2.6 GB for comparable FP16 models |
| CPU inference becomes viable | **Confirmed** | 48 tok/s for 3B model on Surface Laptop (T-MAC) |
| 9-12x energy reduction | **Confirmed** | BitNet 2B: 0.028 J vs 0.258-0.347 J per inference |
| "GPUs are dead" | **False** | GPU tensor cores aren't optimized for ternary; GPUs remain dominant for training and large-scale inference |
| Drop-in replacement for any model | **False** | Must train from scratch with QAT for competitive results |
| Same accuracy at 1-bit | **Partially true** | Competitive on general benchmarks; degrades on coding/STEM tasks |

---

## 2. What "1-Bit" Actually Means

### Precision levels in practice

| Format | Bits/weight | Values | Use case |
|--------|-------------|--------|----------|
| FP32 | 32 | Continuous | Training (legacy) |
| BF16/FP16 | 16 | Continuous | Standard training & inference |
| INT8 | 8 | 256 levels | Production inference (TensorRT-LLM, vLLM) |
| INT4 | 4 | 16 levels | Aggressive quantization (GPTQ, AWQ) |
| Ternary (1.58-bit) | 1.585 | {-1, 0, +1} | BitNet b1.58 |
| Binary (1-bit) | 1.0 | {-1, +1} | PrismML Bonsai, XNOR-Net |

### Why "1.58 bits"

log₂(3) ≈ 1.585. A ternary symbol {-1, 0, +1} carries 1.58 bits of information. The zero state provides **implicit structured sparsity** — approximately 2/3 of weights are zero in practice, meaning the network is simultaneously quantized and pruned.

### Effective storage

Ternary weights require 1.58 bits per weight plus small FP scaling metadata per block/channel. Effective compression vs FP16 is approximately **10x**, not exactly 16x, due to scaling overhead.

---

## 3. Key Research: Microsoft BitNet Family

### BitNet (October 2023)

**Paper:** "BitNet: Scaling 1-bit Transformers for Large Language Models" (arXiv:2310.11453)

- First demonstration that 1-bit weight quantization scales to LLM sizes
- Binary weights {-1, +1} with FP16 activations
- Replaced `nn.Linear` with `BitLinear` layers
- Showed competitive perplexity at 3B parameters

### BitNet b1.58 (February 2024)

**Paper:** "The Era of 1-bit LLMs: All Large Language Models are in 1.58 Bits" (arXiv:2402.17764)

- Upgraded to ternary {-1, 0, +1} via **absmean quantization**
- Formula: `W_q = RoundClip(W / (γ + ε), -1, 1)` where γ = mean(|W|)
- At 3B parameters, matched FP16 LLaMA quality on standard benchmarks
- Architecture: RoPE positional embeddings, squared ReLU (not SwiGLU), subln normalization, no bias terms

### BitNet a4.8 (October 2024)

**Paper:** "BitNet a4.8: 4-bit Activations for 1-bit LLMs" (arXiv:2411.04965)

- Addresses the activation bottleneck — while weights are ternary, activations previously remained at FP16
- Hybrid activation scheme: ~90% of channels at **4-bit**, ~10% outlier channels at **8-bit**
- Enables fully integer arithmetic for the vast majority of operations
- ~55% faster inference vs BitNet b1.58 with FP8 activations
- Perplexity degradation: <0.5 PPL increase on WikiText-2

### BitNet b1.58 2B4T (April 2025)

**Model:** Released on HuggingFace (microsoft/bitnet-b1.58-2B-4T)

The flagship open model: 2B parameters trained on 4T tokens (DCLM, FineWeb-EDU, synthetic math data). Two-stage pre-training with cosine decay, then SFT (WildChat/LMSYS-Chat/WizardLM/SlimOrca), then DPO alignment (UltraFeedback/MagPie).

**Benchmark results:**

| Benchmark | BitNet 2B | LLaMA 3.2 1B | Gemma 3 1B | Qwen 2.5 1.5B |
|-----------|-----------|--------------|------------|----------------|
| MMLU | 53.17 | 45.58 | 39.91 | **60.25** |
| GSM8K | 58.38 | 38.21 | 31.16 | 56.79 |
| HumanEval+ | 38.40 | 31.10 | 37.20 | **50.60** |
| ARC-Challenge | 49.91 | 37.80 | 38.40 | 46.67 |
| Average | 54.19 | 44.90 | 43.74 | **55.23** |

**Efficiency numbers:**

| Metric | BitNet 2B | LLaMA 3.2 1B | Qwen 2.5 1.5B |
|--------|-----------|--------------|----------------|
| Non-embedding memory | **0.4 GB** | 2.0 GB | 2.6 GB |
| CPU decode latency (TPOT) | **29 ms** | 48 ms | 65 ms |
| Energy per inference | **0.028 J** | 0.258 J | 0.347 J |

**Key takeaway:** Beats LLaMA 3.2 1B and Gemma 3 1B convincingly. Roughly on par with Qwen 2.5 1.5B overall (Qwen edges ahead on MMLU and HumanEval+). BitNet has 2x more parameters but uses 6.5x less memory.

**Microsoft's own caveat:** "We do not recommend using BitNet b1.58 in commercial or real-world applications without further testing."

---

## 4. Key Research: PrismML Bonsai

**Released:** March 31, 2026 (emerged from stealth — Caltech spinout)
**License:** Apache 2.0

### Architecture

- Pure binary weights {-1, +1} (not ternary) with shared scale factors per weight group
- Models: Bonsai 8B, 4B, 1.7B
- Runs via llama.cpp (GGUF format) and Apple MLX

### Claimed benchmarks (self-reported, not independently verified)

| Metric | Bonsai 8B | Llama 8B | Ministral3 |
|--------|-----------|----------|------------|
| Average benchmark score | 70.5 | 67.1 | 71.0 |
| Memory | **1.15 GB** | ~16 GB (FP16) | — |
| Intelligence density (their metric) | **1.06/GB** | 0.10/GB | — |

**Caveat:** "Intelligence density" is PrismML's own invention. Benchmark claims are self-reported. No independent verification as of April 2026.

---

## 5. Other 1-Bit / Ultra-Low-Bit Research

### STBLLM (ICLR 2025)

"STructured Binarization for LLMs" — pushes compression **below** 1-bit precision via structured binarization techniques. Opens sub-1-bit edge deployment possibilities.

### PT-BitNet (2025)

Post-training ternary quantization that extends BitNet-style quantization to models up to 70B parameters without training from scratch. Trades some accuracy for dramatically reduced cost of entry.

### Continual Quantization-Aware Pre-Training (February 2025, arXiv:2502.11895)

Hybrid approach: train at 16-bit first, then transition to 1.58-bit quantization-aware training mid-stream. Results suggest this "16-to-1.58-bit" strategy produces better models than full 1.58-bit training from scratch.

### OneBit (NeurIPS 2024, arXiv:2402.11295)

1-bit LLM fine-tuning from pretrained models using rank-1 decomposition plus a sign matrix. Decomposes W ≈ αsᵀ where s is a sign vector — a matrix factorization path to 1-bit weights.

### BinaryBERT (ACL 2021)

Ternary BERT with <2% accuracy loss on GLUE tasks using ternary weight splitting (decomposing pretrained weights into ternary approximations). Demonstrates feasibility for encoder models.

### Notable absence

No major 1-bit-specific papers from Google or Meta as of early 2026. Meta focuses on conventional quantization (GPTQ, AWQ at 4-bit). Google focuses on standard quantization and distillation.

---

## 6. Training Techniques for 1-Bit Models

### The fundamental challenge

Ternary/binary weights are discrete — standard gradient descent requires continuous differentiability. The gradient of a `sign()` or `round()` function is zero almost everywhere, making backpropagation impossible without workarounds.

### Straight-Through Estimator (STE)

**Origin:** Bengio et al. (arXiv:1308.3432, 2013)

The dominant approach: during the forward pass, weights are quantized to {-1, 0, +1}. During backward pass, the gradient passes through the quantization function as if it were the identity (gradient ≈ 1 within a clipping range, 0 outside). Latent full-precision weights are maintained and updated by the optimizer.

### Quantization-Aware Training (QAT) for BitNet

1. Maintain full-precision "latent weights" during training
2. Each forward pass quantizes via absmean: `W_q = RoundClip(W / mean(|W|), -1, 1)`
3. Activations are group-quantized to INT8 per token
4. Gradients update the latent weights via STE
5. Training proceeds from **random initialization** — not from a pretrained FP16 model

### Post-training vs native training

**Critical distinction that determines quality:**

| Approach | Quality at ~1.5 bits | Cost | Flexibility |
|----------|---------------------|------|-------------|
| Native QAT (BitNet) | Near FP16 parity at 3B+ | Full pre-training budget | Must train from scratch |
| Post-training quantization | Severe degradation | Minimal (hours) | Any existing model |
| Continual QAT (16→1.58 bit) | Between the two | Partial pre-training | Start from checkpoint |
| PT-BitNet (post-training ternary) | Moderate degradation | Low | Up to 70B models |

### Advanced training approaches

- **Two-stage knowledge distillation:** FP16 teacher guides binary student training (Liu et al., ICML 2020)
- **Bi-Real Net (arXiv:1808.00278):** Shortcut connections preserving real-valued information alongside binary weights
- **ReActNet (ECCV 2020):** Distribution reshaping and channel-wise shifts before sign activation
- **IR-Net (CVPR 2020):** Balanced binary quantization maximizing information entropy
- **AdaBin (2022):** Learned per-channel quantization thresholds rather than fixed sign(0)

---

## 7. Theoretical Foundations

### Information theory perspective

**Why 1.58 bits works:** Neural network weights follow approximately Gaussian/Laplacian distributions. Ternary quantization captures:
- The **sign** of the weight (most important information)
- A **zero/non-zero** distinction enabling implicit pruning
- Scaling factors per block recover magnitude information

### Minimum bits per weight

Rate-distortion theory sets the lower bound: R(D) = ½ log(σ²/D) for Gaussian-distributed weights. Empirically, multiple papers converge on a **"quality cliff" at ~1.5-2 bits per weight** — below this, perplexity degrades rapidly; above it, returns diminish. BitNet b1.58 at 1.58 bits sits remarkably close to this empirical threshold.

### Universal approximation

Qin et al. (ICLR 2020) proved that binary neural networks are **universal approximators** with sufficient width — there is no theoretical barrier to 1-bit quality, only practical training challenges.

### Optimal bit allocation

- **HAWQ** (arXiv:1905.03696): Uses Hessian eigenvalues to determine which layers need more bits — layers with higher curvature are more quantization-sensitive
- **OBQ** (arXiv:2208.11580): Second-order methods for theoretically optimal per-weight bit allocation
- **GPTQ** (arXiv:2210.17323): Extended OBQ for LLMs, processing weights in blocks — foundational for many subsequent methods

---

## 8. Practical Tooling & Inference Engines

### bitnet.cpp (Microsoft)

**GitHub:** microsoft/BitNet — forked from llama.cpp with specialized ternary kernels.

Standard llama.cpp **cannot** run native BitNet models — the ternary weight scheme requires custom kernels.

**Performance:**
- x86 CPUs: 2.37-6.17x speedup vs FP16, 71.9-82.2% energy reduction
- ARM CPUs: 1.37-5.07x speedup, 55.4-70.0% energy reduction
- 100B BitNet model on single CPU: ~5-7 tok/s (human reading speed)
- January 2026 update: parallel kernel implementations with configurable tiling, additional 1.15-2.1x speedup
- April 2025: CUDA GPU kernel support added

### T-MAC (2026)

Library for running low-bit LLMs on standard CPUs. Achieves **48 tok/s** for a 3B BitNet model on a Surface Laptop 7 — outperforms llama.cpp by 4-5x on this workload.

### llama.cpp (GGUF ecosystem)

As of v1.72 (2026): supports 1.5-bit to 8-bit integer quantization generally. PrismML Bonsai models run natively via GGUF format. But native BitNet b1.58 models still require bitnet.cpp's specialized kernels.

### MLX (Apple)

Apple's ML framework; PrismML Bonsai runs natively on Apple Silicon. No native BitNet b1.58 support.

### What's NOT supported

No support in production serving stacks: **vLLM, TensorRT-LLM, Triton Inference Server, or SGLang** — a major barrier to production adoption.

---

## 9. llama.cpp Extreme Quantization Ecosystem

### Post-training ultra-low-bit formats

| Format | Bits/weight (avg) | Method | WikiText-2 PPL (7B) |
|--------|-------------------|--------|---------------------|
| FP16 | 16.0 | Full precision | ~5.7 |
| Q4_K_M | ~4.5 | k-quants (group) | ~5.8 |
| IQ2_M | ~2.7 | Importance-weighted | ~7.0 |
| IQ2_XXS | ~2.0625 | Importance-weighted | ~7.5-8.5 |
| IQ1_M | ~1.75 | Importance + trellis | ~10-12 |
| IQ1_S | ~1.5625 | Importance + trellis | ~12-15 |

### How IQ formats work

1. **Importance matrix (imatrix):** Calibration dataset computes per-weight importance scores (Hessian diagonal / activation magnitudes)
2. **Trellis quantization:** Groups of weights are jointly quantized using lattice coding from digital communications theory
3. **Lookup tables:** Weights encoded as indices into small codebooks (vector quantization)

### PTQ vs native QAT comparison

| Approach | Quality at ~1.5 bits (7B) | Available for | Memory |
|----------|---------------------------|---------------|--------|
| IQ1_S (llama.cpp PTQ) | PPL ~12-15 (severe degradation) | Any GGUF model | ~1.3 GB |
| BitNet b1.58 (native QAT) | PPL matches FP16 at 3B+ | Only BitNet-trained models | ~0.4 GB (2B) |

**Conclusion:** Native 1-bit training is dramatically superior to post-training quantization at the same bit level. IQ1_S is available now for any model but quality suffers severely. BitNet models require from-scratch training but preserve quality.

### Related PTQ research

- **QuIP#** (arXiv:2402.04396): Near-lossless 2-bit PTQ using E8 lattice codebooks + incoherence processing
- **AQLM** (2024): Additive multi-codebook quantization, competitive at 2 bits

---

## 10. Hardware for 1-Bit Inference

### The hardware mismatch problem

Current GPUs (NVIDIA A100, H100, etc.) have tensor cores optimized for FP16/BF16/INT8 matrix multiply. Ternary operations ({-1, 0, +1} × activation = sign-flip, zero, or identity) reduce to **additions**, but GPU hardware still routes them through multiply-accumulate units. The efficiency gains of 1-bit are primarily realized on **CPUs** where memory bandwidth is the dominant bottleneck.

### CPU inference (current sweet spot)

| Platform | Key feature | 1-bit advantage |
|----------|-------------|-----------------|
| x86 (AVX-512) | 512-bit SIMD | Lookup-table kernels for ternary ops |
| x86 (AMX) | Matrix extensions | Potential for INT2-aware tiling |
| ARM (NEON/SVE) | Mobile/edge SIMD | Low-power ternary inference |
| Apple Silicon (M-series) | Unified memory, high bandwidth | Large models fit in unified RAM |

### FPGA implementations

- **FINN framework (AMD/Xilinx):** Purpose-built for binary/ternary networks. Up to **12.3 TOPs** on ZCU104 for binary networks using XNOR-popcount
- **LUTNet:** Maps binary operations directly to FPGA lookup tables
- **hls4ml:** Open-source tool for ultra-low-precision NN on FPGAs, used at CERN for real-time inference

### Custom silicon (in-memory computing)

- **XNOR-SRAM designs:** SRAM cells performing XNOR operations natively (Samsung, TSMC research)
- **Processing-in-Memory (PIM):** Eliminates data movement entirely — compute happens where weights are stored
- Microsoft explicitly calls for purpose-built 1-bit silicon, estimating **10-100x** energy efficiency gain over repurposed GPU hardware

### Novel architectures

| Architecture | Current status | 1-bit relevance |
|-------------|---------------|-----------------|
| **Cerebras WSE-3** | 40 GB on-chip SRAM, sparse-optimized | Natural fit — sparse ternary weights; no published 1-bit benchmarks |
| **Groq LPU** | SRAM-based, deterministic latency | No HBM = memory bandwidth not bottleneck; could fit much larger 1-bit models on-chip |
| **Intel Gaudi** | INT8-optimized | No specific 1-bit support |
| **Apple Neural Engine** | INT8/INT4 target | No 1-bit support via MLX yet |

---

## 11. Domain-Specific Results

Published results are limited. Most benchmarks cover general language modeling, reasoning, and commonsense. Domain-specific findings:

### Where 1-bit works well

- **Classification / intent detection:** Binary/ternary networks have strong history here. BinaryBERT achieves <2% accuracy loss on GLUE. Excellent candidate for edge deployment.
- **Commonsense reasoning:** BitNet 2B matches or beats comparable FP16 models on ARC, HellaSwag, WinoGrande, PIQA.
- **Math (GSM8K):** BitNet 2B scores 58.38, beating LLaMA 3.2 1B (38.21) and Gemma 3 1B (31.16).

### Where 1-bit struggles

- **Code generation:** BitNet 2B scores 38.4 on HumanEval+ vs Qwen 1.5B's 50.6 — code requires precise token prediction and is more quantization-sensitive.
- **Complex STEM tasks:** Generally show the largest degradation from quantization across the literature.
- **Long-context tasks:** BitNet 2B4T has not been evaluated on extended sequence lengths. Microsoft notes this as unexplored.
- **Multilingual:** BitNet 2B4T is English-focused. No multilingual 1-bit models exist.

### Unexplored domains

- Translation (constrained output space may be more forgiving)
- Summarization (ROUGE metrics are more forgiving than perplexity)
- Tool calling / function calling (no published benchmarks)
- Agent workflows (no published benchmarks)

---

## 12. Speculative Decoding with 1-Bit Draft Models

### The opportunity

Speculative decoding (Leviathan et al., arXiv:2211.17192) uses a small "draft" model to generate K candidate tokens, verified in parallel by the large "target" model. Draft models need to be (a) fast and (b) reasonably distribution-aligned. 1-bit models excel at (a).

### Why 1-bit draft models are a natural fit

- **Memory overhead:** A 1-bit 1B draft model uses ~125 MB — negligible next to a 70B target model
- **Speed:** 1-bit inference on CPU is 5-10x faster than FP16 of the same size
- **Latency:** Drafting phase becomes near-instantaneous
- **Trade-off:** Higher KL divergence from FP16 target → lower acceptance rate, but raw speed compensates

### Related work

- **EAGLE** (arXiv:2401.15077): Lightweight draft heads (could be made 1-bit)
- **Medusa** (arXiv:2401.10774): Multiple parallel draft heads (natural candidates for 1-bit)
- **TriForce** (arXiv:2404.11912): Hierarchical speculative decoding with aggressive approximation

### Status

No published paper specifically combining BitNet-style 1-bit models as speculative decoding drafts. This is an **open research opportunity** — likely being explored by multiple groups.

---

## 13. Competing Approaches: Pruning, Distillation, MoE

### Comparison table

| Method | Memory Reduction | Compute Reduction | Quality Impact | Complementary with 1-bit? |
|--------|-----------------|-------------------|----------------|--------------------------|
| **1-bit quantization** | ~10x | ~10x (add-only) | Minimal at 3B+ (native QAT) | N/A |
| **Pruning (50% sparse)** | ~2x | ~1.5-2x | Minimal | Yes |
| **Knowledge distillation** | 10-100x fewer params | Proportional | Moderate-significant | Yes |
| **MoE (e.g., 8x7B)** | None (memory) | ~4-8x (active) | Minimal | **Very promising** |
| **Low-rank factorization** | ~2-4x | ~2-4x | Moderate | Partially |

### Key insights

1. **1-bit + MoE is the most promising combination:** MoE reduces active computation (sparse expert routing) while 1-bit reduces memory per parameter. A 1-bit MoE model would have tiny memory footprint AND sparse computation. No published work on this combination for LLMs yet.

2. **1-bit + pruning is partially redundant:** BitNet b1.58 weights are ~2/3 zeros already (implicit sparsity from the ternary quantization). Additional pruning may have diminishing returns.

3. **1-bit + distillation is complementary:** Distill a large model into a smaller architecture, then train that architecture with 1-bit QAT. This could yield a 1-bit 3B model that captures knowledge from a 70B teacher.

### Specific competing methods

- **SparseGPT** (arXiv:2301.00774): 50-60% unstructured sparsity with minimal perplexity increase
- **Wanda** (arXiv:2306.11695): One-shot pruning by weights and activations, comparable to SparseGPT
- **GaLore** (arXiv:2403.03507): Gradient low-rank projection for memory-efficient training

---

## 14. Energy & Sustainability Impact

### Per-operation energy costs

From Horowitz (ISSCC 2014), the widely-cited reference for operation energy in 45nm technology:

| Operation | Energy (picojoules) | Relative to FP16 multiply |
|-----------|--------------------|-----------------------------|
| FP32 multiply | ~3.7 pJ | 4.1x |
| FP16 multiply | ~0.9 pJ | 1.0x (baseline) |
| INT8 multiply | ~0.2 pJ | 0.22x |
| INT8 add | ~0.03 pJ | 0.03x |
| Ternary op (lookup + add) | ~0.02-0.05 pJ | 0.02-0.06x |

**Key insight:** 1-bit inference replaces multiplications with additions. For ternary weights, multiply by {-1, 0, +1} is sign-flip, zero, or identity — no multiplier circuits needed.

### Measured energy savings

- **bitnet.cpp:** 55.4% to 82.2% energy reduction vs FP16 on CPU inference
- **BitNet 2B:** 0.028 J per inference vs 0.258 J (LLaMA 1B) and 0.347 J (Qwen 1.5B) — **9-12x reduction**
- **Memory access dominates:** Memory read energy exceeds compute energy by roughly 10:1 in LLM inference. 1-bit models use ~10x less memory bandwidth, so total system energy savings are **5-10x**.

### Datacenter-scale projections

- Global datacenter electricity: ~460 TWh in 2024, projected >1,000 TWh by 2026 (IEA)
- AI inference is 15-25% of hyperscaler datacenter energy (Meta reported figures)
- Conservative **4x energy reduction** for inference → 25-40% reduction in AI inference energy
- For a hyperscaler spending ~$2B/year on AI inference electricity: **$500M-$800M annual savings**

---

## 15. Real-World Deployment Status

### As of April 2026: No confirmed production deployments

- Microsoft explicitly warns against production use of BitNet
- PrismML is the first company positioning 1-bit for commercial use (edge/robotics/real-time agents), but just emerged from stealth — no production case studies
- Largest publicly available native 1-bit model: **8B parameters** (PrismML Bonsai)
- No support in production serving frameworks (vLLM, TensorRT-LLM, Triton, SGLang)

### Barriers to production

1. **From-scratch training cost:** Full pre-training budgets required (millions of dollars for 70B+)
2. **Tooling immaturity:** bitnet.cpp and T-MAC only; no production serving integration
3. **Scale gap:** 8B is the ceiling; frontier models are 70B-400B+
4. **Fine-tuning story:** How to efficiently adapt 1-bit models (LoRA for ternary weights?) is underexplored
5. **No RL alignment:** Only DPO has been applied; PPO/GRPO impact unknown
6. **Verification gap:** PrismML's claims are self-reported; limited independent benchmarking

---

## 16. Implications for This Project

### Architecture readiness

The micro-x-agent-loop-python architecture is **already well-positioned** for 1-bit models:

| Feature | How it helps 1-bit integration |
|---------|-------------------------------|
| `ProviderPool` multi-provider dispatch | Add 1-bit models as another provider target |
| `SemanticClassifier` 3-stage routing | Route cheap tasks to 1-bit, complex tasks to capable models |
| `RoutingPolicies` per-task-type config | Zero code changes — just config |
| `OllamaProvider` (OpenAI-compatible) | 1-bit models via Ollama or similar local server |
| `tool_search_only` flag | Narrow tools for small models that can't handle complex schemas |
| `system_prompt: "compact"` | Minimal prompts for tight context windows |
| `pin_continuation` | Prevent model switching mid-turn |
| Confidence gating (`RoutingConfidenceThreshold`) | Refuse downgrade to 1-bit if classification isn't confident |
| Cost tracking with configurable `Pricing` | Set (0, 0, 0, 0) for free local inference |

### Multi-tier routing strategy

The existing `CHEAP_TASK_TYPES` / `MAIN_TASK_TYPES` split maps directly to a 1-bit integration:

```
[1-bit local model — 0.4 GB, 29ms/token, $0.00]
  → trivial, conversational, factual_lookup, summarization
  → tool_search_only: true, system_prompt: "compact"

[Mid-tier API model — Haiku/Flash]
  → code_review, summarization (complex), analysis (simple)

[Full-capability model — Sonnet/Opus]
  → code_generation, analysis (complex), creative, tool_continuation
```

### Example config (when models are available)

```json
"RoutingPolicies": {
  "trivial":        { "provider": "ollama", "model": "bitnet-2b", "tool_search_only": true, "system_prompt": "compact" },
  "conversational": { "provider": "ollama", "model": "bitnet-2b", "tool_search_only": true, "system_prompt": "compact" },
  "factual_lookup": { "provider": "ollama", "model": "bonsai-4b", "tool_search_only": true },
  "summarization":  { "provider": "ollama", "model": "bonsai-4b" },
  "code_generation": { "provider": "#Provider", "model": "#Model" },
  "code_review":     { "provider": "#Provider", "model": "#Model" },
  "analysis":        { "provider": "#Provider", "model": "#Model" },
  "creative":        { "provider": "#Provider", "model": "#Model" }
}
```

### What to watch for actionability

1. **Ollama support for BitNet/Bonsai models** — when these appear in Ollama's model library, integration is trivial
2. **Tool-calling quality** — our findings with qwen2.5:7b (see [local-model-hardware-options.md](local-model-hardware-options.md)) showed 7B models struggle with complex tool schemas. 1-bit models at similar parameter counts will likely have the same limitation. The `tool_search_only` mitigation already exists.
3. **Speculative decoding** — if vLLM/SGLang add 1-bit draft model support, this could accelerate our API inference at near-zero additional cost

### Relationship to existing cost optimization

This research extends the strategies documented in [cost-reduction-research-report.md](cost-reduction-research-report.md):
- **Section 2 (Route Tasks to Right Model):** 1-bit models are the logical extreme of "cheap model for routine steps"
- **Section 5 (Split Stack by Task Type):** 1-bit models become the cheapest tier — literally $0.00/token for local inference
- **Section 6 (Cheaper Second Provider):** Local 1-bit inference eliminates API costs entirely for routed tasks

---

## 17. Timeline & Maturity Assessment

### Predicted vs actual (calibrating forecasts)

Predictions from early 2025 research papers, evaluated against April 2026 reality:

| Prediction | Expected | Actual (April 2026) | Accuracy |
|-----------|----------|---------------------|----------|
| 1-bit results at 13B scale | Q2-Q3 2025 | Not published yet | Missed |
| 1-bit results at 70B scale | Q4 2025-Q2 2026 | PT-BitNet only (post-training, with degradation) | Partially met |
| Open-source 1-bit checkpoints (7B+) | Q3 2025-Q1 2026 | PrismML Bonsai 8B (March 2026) | Met (late) |
| GPU-optimized inference kernels | Q2-Q4 2025 | bitnet.cpp CUDA (April 2025) | Met |
| Production deployment at hyperscaler | 2026-2027 | Not yet | On track (unconfirmed) |

### Forward-looking assessment

| Milestone | Estimate | Confidence |
|-----------|----------|------------|
| Native 1-bit models at 13-30B | H2 2026 | Medium-High |
| Native 1-bit at 70B+ | 2027 | Medium |
| vLLM/TensorRT-LLM integration | H2 2026 - H1 2027 | Medium |
| Ollama catalog support for 1-bit | H2 2026 | High |
| 1-bit MoE models | 2027+ | Speculative |
| Custom 1-bit silicon | 2028+ | Speculative |
| Widespread production adoption | 2028+ | Speculative |

### Recommendation

**Do not invest engineering effort in 1-bit integration now.** The architecture already supports it via config. When 1-bit models appear in Ollama's catalog with acceptable tool-calling quality, integration is a config change — not a code change. Monitor:
- Ollama model library for BitNet/Bonsai models
- bitnet.cpp and T-MAC releases
- vLLM speculative decoding with 1-bit drafts

---

## 18. References

### Core papers

| Paper | ID | Date |
|-------|----|------|
| BitNet: Scaling 1-bit Transformers for LLMs | arXiv:2310.11453 | Oct 2023 |
| The Era of 1-bit LLMs (BitNet b1.58) | arXiv:2402.17764 | Feb 2024 |
| BitNet a4.8: 4-bit Activations for 1-bit LLMs | arXiv:2411.04965 | Oct 2024 |
| BitNet b1.58 2B4T Technical Report | arXiv:2504.12285 | Apr 2025 |
| bitnet.cpp: Efficient Edge Inference (ACL 2025) | ACL 2025 proceedings | 2025 |
| OneBit (NeurIPS 2024) | arXiv:2402.11295 | Feb 2024 |
| STBLLM: Breaking the 1-Bit Barrier (ICLR 2025) | ICLR 2025 proceedings | 2025 |
| PT-BitNet: Post-Training Quantization for BitNet | ScienceDirect | 2025 |
| Continual Quantization-Aware Pre-Training | arXiv:2502.11895 | Feb 2025 |

### Quantization foundations

| Paper | ID | Date |
|-------|----|------|
| GPTQ: Accurate Post-Training Quantization | arXiv:2210.17323 | Oct 2022 |
| QuIP#: 2-bit Quantization with E8 Lattice | arXiv:2402.04396 | Feb 2024 |
| HAWQ: Hessian-Aware Quantization | arXiv:1905.03696 | 2020 |
| OBQ: Optimal Brain Quantization | arXiv:2208.11580 | 2022 |
| STE: Estimating Gradients Through Stochastic Neurons | arXiv:1308.3432 | 2013 |

### Competing methods

| Paper | ID | Date |
|-------|----|------|
| SparseGPT: One-Shot LLM Pruning | arXiv:2301.00774 | Jan 2023 |
| Wanda: Pruning by Weights and Activations | arXiv:2306.11695 | Jun 2023 |
| GaLore: Gradient Low-Rank Projection | arXiv:2403.03507 | 2024 |
| Speculative Decoding | arXiv:2211.17192 | Nov 2022 |
| EAGLE: Speculative Sampling | arXiv:2401.15077 | Jan 2024 |
| Medusa: Multiple Decoding Heads | arXiv:2401.10774 | Jan 2024 |

### Hardware and energy

| Source | Context |
|--------|---------|
| Horowitz, ISSCC 2014 | Canonical reference for operation energy costs |
| IEA World Energy Outlook 2024 | Datacenter electricity projections |
| Luccioni et al. (arXiv:2311.16863) | Measured inference energy across model sizes |
| Patterson et al. (arXiv:2104.10350) | Training carbon footprint analysis |

### Industry sources

| Source | Context |
|--------|---------|
| Microsoft BitNet GitHub (microsoft/BitNet) | Official inference framework |
| HuggingFace: microsoft/bitnet-b1.58-2B-4T | Model card and benchmarks |
| PrismML announcement (prismml.com) | Bonsai model family |
| The Register (April 4, 2026) | PrismML coverage |
| HPCwire (April 3, 2026) | PrismML industry analysis |

---

*Related research in this directory:*
- [cost-reduction-research-report.md](cost-reduction-research-report.md) — Multi-model cost optimization strategies
- [local-model-hardware-options.md](local-model-hardware-options.md) — Local inference hardware, qwen2.5:7b findings, Ollama integration
- [key-insights-and-takeaways.md](key-insights-and-takeaways.md) — Cross-framework synthesis
