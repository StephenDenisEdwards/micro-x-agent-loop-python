# Compaction in Agent Loops

## Executive summary

“Compaction” in an agent loop is any deliberate transformation that reduces what the agent carries forward (prompt tokens, persisted memories, or internal serving state) while attempting to preserve *decision-relevant* information. In practice, compaction is not one technique but a design space spanning: (i) prompt/token compaction (reduce input length), (ii) memory compaction (reduce long-term stores), (iii) explicit state compaction (reduce structured state and tool artefacts), and (iv) model-serving state compaction (reduce inference-time caches such as Transformer KV caches). citeturn8view0turn6view0turn17view0turn18view0

Several independent pressures make compaction central to production agent design: context windows are finite; long histories make models slower and often less reliable; repeated prefixes create opportunities for caching; and long-context inference is frequently bottlenecked by KV cache growth (GPU memory, bandwidth, and time-to-first-token). citeturn8view0turn6view3turn7view1turn17view0turn18view0

The most “bang-for-buck” compaction in deployed systems usually comes from hybrid engineering patterns rather than exotic algorithms: (1) place stable instructions early to maximise prompt cache hits; (2) keep structured state outside the prompt and render only the minimal slice needed per step; (3) trim and summarise short-term history; (4) store long-term facts/episodes in a retrievable store and prune/deduplicate that store; (5) checkpoint agent state to enable reproducibility and controlled recovery from compaction failures. citeturn6view3turn7view1turn8view0turn9view0turn11search2

The dominant risks are *information loss* and *semantic drift*: summarisation can hallucinate or omit constraints; retrieval can become redundant (top‑k near-duplicates) or overly aggressive pruning can delete “prerequisite” evidence chains; and opaque “black-box” compaction (e.g., encrypted compaction items) may reduce inspectability and complicate debugging. citeturn4search0turn11search2turn19view2

A rigorous evaluation programme should measure: end-to-end task accuracy; memory recall and conflict handling; semantic fidelity of compressed representations; latency (TTFT, p50/p95) and token costs; and memory footprint (persistent store size and inference KV-cache footprint, if relevant). Existing memory-agent benchmarks (e.g., LoCoMo, LongMemEval, MemoryAgentBench, PerLTQA) are particularly useful because they stress multi-session recall, temporal reasoning, knowledge updates, and selective forgetting—exactly where compaction failures surface. citeturn12search0turn12search1turn11search17turn12search2

## Definitions and scope

An “agent loop” is an iterative control cycle in which an LLM-driven policy repeatedly (a) observes the current situation (user message, tool outputs, environment state), (b) decides on an action (generate text, call tools, delegate to sub-agents), (c) updates internal state/memory, and (d) continues until termination. In graph-based agent runtimes, this often corresponds to discrete “steps” or “super-steps” whose state can be persisted for resumption and debugging. citeturn9view0turn8view2turn8view3

A useful minimal decomposition of “what the agent carries” per iteration is:

- **Prompt/context (token stream)**: the *serialised* information fed into the model for the current step (messages, retrieved snippets, tool results, system instructions). citeturn8view0turn6view2  
- **Explicit state**: structured variables in the agent runtime (e.g., slots, plans, tool artefacts, message objects, retrieved-doc objects, intermediate calculations). Frameworks increasingly formalise this state and persist it across steps. citeturn8view0turn9view0turn8view3  
- **Long-term memory store**: a separate store (vector store, key-value store, graph store) holding facts, preferences, episodes, and derived summaries across sessions/threads. citeturn8view0turn9view0turn13view5turn11search0  
- **Model-serving internal state**: inference-time caches (notably KV caches) that grow with context length and drive significant memory/latency costs in long-context settings. citeturn18view0turn17view0turn3search1  

### What “compaction” means

In this report, **compaction** is any operator \(C\) that maps an agent’s carry-forward representation \(X\) to a smaller representation \(X’\) under an explicit *budget* (token budget, storage budget, latency budget), while trying to preserve *utility for future decisions*. This includes:

- **Token compaction** (prompt compression): reduce the number of input tokens (e.g., token dropping, prompt compression, summarised history + recent window). citeturn15view0turn10view0turn6view0  
- **Memory compaction**: reduce the growth of persistent memory (deduplicate, prune, merge, consolidate into higher-level notes). citeturn11search2turn13view5turn11search0  
- **State compaction**: compress explicit state (e.g., replace large tool outputs with canonical structured records, store references + hashes, keep deltas). citeturn9view0turn19view2  
- **Serving-state compaction**: reduce inference caches (KV cache quantisation/encoding, eviction, residual/delta coding). citeturn18view0turn17view0  

Compaction can be:

- **Lossless**: exact reconstruction of the original \(X\) is possible (e.g., checkpoint+delta logs, byte-level compression for storage, prompt prefix caching of already-computed activations). citeturn6view3turn9view0turn18view0  
- **Lossy**: the transformation discards or rewrites information (summaries, token dropping, merging memories), trading fidelity for efficiency. citeturn10view0turn15view0turn11search2  

```mermaid
flowchart LR
  U[User / Environment] --> O[Observe]
  O -->|messages, tool outputs| S[Explicit State]
  S --> P[Prompt Builder]
  M[(Long-term Memory Store)] --> R[Retrieve/Filter]
  R --> P
  P --> LLM[LLM Policy]
  LLM --> A[Act: text / tools / delegation]
  A --> O

  subgraph Compaction
    C1[Token compaction\n(trim/summarise/compress)]
    C2[Memory compaction\n(prune/merge/consolidate)]
    C3[State compaction\n(snapshot/delta/hashes)]
    C4[Serving-state compaction\n(KV cache encode/evict)]
  end

  S -.-> C3 -.-> S
  P -.-> C1 -.-> P
  M -.-> C2 -.-> M
  LLM -.-> C4
```

## Motivations

### Context-window limits and “distraction” effects

Even when a model technically supports very long inputs, long conversational histories often harm practical performance: they increase cost/latency and may “distract” models with stale or off-topic details. This is why many agent frameworks explicitly recommend trimming, forgetting, or summarising conversational history rather than always passing full history. citeturn8view0turn6view0

### Latency and token-cost economics

Token costs scale (roughly) with the number of input tokens processed per turn, and latency often scales with both input length and model size. The strongest production wins often come from: (a) reducing prompt length and (b) maximising reuse of repeated prefixes.

A concrete example is **prompt caching**: caching is only possible for exact prefix matches, so placing static content (system instructions, shared examples) at the beginning and variable content (retrieval results, user-specific data) later improves cache hit rates. OpenAI’s prompt caching guidance reports latency reductions “up to 80%” and input token cost reductions “up to 90%” under cache hits, with caching automatically enabled above a token threshold and using prefix hashing/routing. citeturn6view3turn7view1turn2search1

### Retrieval efficiency in agent memory is *not* classical RAG

A key research insight from recent agent-memory work is that “agent memory” differs from the standard RAG setting: instead of a huge heterogeneous corpus, an agent often has a bounded dialogue stream with highly correlated spans and near duplicates. In that regime, naive top‑k similarity retrieval often returns redundant context, and pruning can delete prerequisites in a multi-step evidence chain, hurting correctness. citeturn11search2turn11search6

### Serving constraints: KV-cache growth, bandwidth, and TTFT

Long-context generation is often bottlenecked by the cost of processing the prompt (prefill) and by the growth of the Transformer KV cache with sequence length. CacheGen frames this as a “context-loading” bottleneck: nothing can be generated until the full context is processed, and KV caches are large tensors whose transfer can dominate latency if cached states must be fetched across machines. CacheGen reports multi‑× reductions in KV-cache size and TTFT by encoding KV caches into compact bitstreams (quantisation + arithmetic coding, exploiting locality) and streaming strategies. citeturn18view0turn11search3

More recent KV-cache work (e.g., DeltaKV) highlights that KV cache memory grows linearly with context length and can exceed accelerator memory at large context lengths/batch sizes, motivating compression beyond token eviction. citeturn17view0turn5search0

## Techniques and algorithms

The techniques below are organised by what they compact (tokens, memory, state, or serving caches). For each, “algorithm” describes a generic implementation pattern; concrete systems may vary.

### Token-level compression

**What it compacts**: the *prompt token stream* (the immediate context provided to the LLM). citeturn15view0turn16view0turn10view0

**Core idea**: reduce prompt length while retaining the parts most predictive of correct output.

**Representative approaches and primary sources**

- **Perplexity/importance-based token dropping (LLMLingua)**: LLMLingua proposes a coarse-to-fine prompt compression method with (i) a budget controller that allocates different compression ratios to prompt components and (ii) an iterative token-level procedure that accounts for conditional dependencies across segments. citeturn15view0  
- **Learned “gist tokens” (gisting)**: trains a model to compress prompts into a small set of “gist” tokens by inserting special tokens and modifying the attention mask so later tokens cannot attend to the original prompt; the model must encode prompt information into the gist token activations. The paper reports up to 26× compression and associated FLOPs/latency savings. citeturn16view0  
- **Prefix compute reuse (prompt caching)**: not a “compression” of text, but a *compute compaction* that benefits repeated prefixes; requires exact prefix matches and careful prompt structuring. citeturn6view3turn7view1  

**Algorithm sketch: LLMLingua-style budget + iterative token compression**

LLMLingua’s paper provides pseudocode for a budget controller (Algorithm 1) and an iterative token-level prompt compression (Algorithm 2), using a small model’s perplexity estimates to decide what to preserve at different granularities. citeturn15view0

```python
def compress_prompt_llmlingua_style(prompt_parts, small_lm, target_rate,
                                   instr_rate=0.8, question_rate=0.8,
                                   demo_granularity=1.02, segment_tokens=256):
    """
    prompt_parts: {"instruction": str, "demos": [str], "question": str}
    Returns compressed_prompt: str
    """
    # 1) Coarse budget allocation: keep more budget for instruction/question, less for demos.
    demos = prompt_parts["demos"]
    demo_budget_rate = derive_demo_rate(target_rate, instr_rate, question_rate, prompt_parts)

    # 2) Demonstration-level selection based on demo perplexity under small_lm.
    scored = [(demo, perplexity(small_lm, demo)) for demo in demos]
    scored.sort(key=lambda x: x[1], reverse=True)  # higher PPL = more "informative" in LLMLingua framing

    selected = []
    max_demo_tokens = int(demo_budget_rate * token_count("".join(demos)) * demo_granularity)
    running = 0
    for demo, _ppl in scored:
        t = token_count(demo)
        if running + t > max_demo_tokens:
            break
        selected.append(demo)
        running += t

    # 3) Adjust remaining budgets for instruction/question after demo selection.
    instr_budget, q_budget = adjust_remaining_budgets(target_rate, instr_rate, question_rate,
                                                      selected, prompt_parts)

    # 4) Fine-grained iterative token compression over segments.
    draft = assemble_prompt(prompt_parts["instruction"], selected, prompt_parts["question"])
    segments = split_into_token_segments(draft, segment_tokens)

    kept_tokens = []
    for seg in segments:
        # Condition on already-kept tokens to reduce independence errors.
        ctx = detokenize(kept_tokens)
        token_ppls = conditional_token_ppl(small_lm, ctx, seg)
        thresh = compute_dynamic_threshold(token_ppls, target_rate_for_segment(seg, instr_budget, q_budget))
        kept_tokens.extend([tok for tok, ppl in token_ppls if ppl > thresh])

    return detokenize(kept_tokens)
```

**Compute and storage costs**

- Importance scoring requires at least one forward pass of a “small LM” over the input (and possibly multiple passes if iterative). LLMLingua explicitly positions this against settings where the target model is API-only and cannot be modified. citeturn15view0  
- Gist tokens require training (or using a gist-trained model) and slightly modified inference, but then gist activations can be cached like a soft prompt/prefix. citeturn16view0  

**Typical hyperparameters**

- Target compression rate / token budget (global and per-component). citeturn15view0  
- Segment length for iterative compression (trade-off between speed and dependency modelling). citeturn15view0  
- Number of gist tokens \(N_g\) and the masking scheme. citeturn16view0  
- Minimum retained “anchors” (system constraints, safety rules, schema instructions)—usually hand-pinned.

**Tuning guidance**

- Allocate budgets by *error sensitivity* not by raw length: system constraints and tool schemas are often brittle and should be preserved verbatim; long exemplars and redundant tool logs are usually the first candidates for compression. citeturn7view1turn6view0  
- Evaluate compression under *distribution shift*: LLMLingua explicitly discusses aligning the compressor distribution to the target LLM to reduce mismatch. citeturn15view0  
- For gist tokens, tune \(N_g\) to match “prompt entropy”: more diverse instructions generally need more gist capacity. citeturn16view0  

**When to use**

- High-volume systems with large repeated prefixes (strong synergy with prompt caching). citeturn6view3turn7view1  
- Tool-heavy workflows where raw tool logs dominate prompt length and iterative context grows quickly. citeturn6view1turn6view0  

### Semantic summarisation

**What it compacts**: conversational history and other text-like traces (observation logs, tool outputs) into a shorter “working memory” representation. citeturn10view0turn8view2turn6view0

**Representative implementations**

- **Running-summary + recent window (LangChain ConversationSummaryBufferMemory)**: stores a running summary plus the most recent messages, ensuring the total token count stays under a limit; the reference implementation exposes `max_token_limit` and maintains a moving summary buffer. citeturn10view0turn10view1  
- **Sequential multi-agent carryover summaries (AutoGen)**: after a chat ends, a summariser produces a summary; sequential chats pass accumulated summaries forward via “carryover”; the default summary method can be “last message” or LLM-based reflection summarisation. citeturn8view2  
- **Session-level trimming and compression (OpenAI Agents SDK cookbook)**: explicitly motivates trimming and compression as context-management tactics to keep agents fast, reliable, and cost-efficient. citeturn6view0  

**Algorithm sketch: summary buffer (progressive summarisation + window)**

```python
class SummaryBuffer:
    def __init__(self, summariser_llm, max_tokens=2000, window_tokens=600):
        self.summariser = summariser_llm
        self.max_tokens = max_tokens
        self.window_tokens = window_tokens
        self.summary = ""
        self.recent = []  # list of message dicts

    def append(self, role, content):
        self.recent.append({"role": role, "content": content})
        self._maybe_compact()

    def context(self):
        # Return summary + recent window for prompt building.
        return render_summary(self.summary) + render_messages(self.recent)

    def _maybe_compact(self):
        while token_count(self.context()) > self.max_tokens:
            # Move oldest messages into the rolling summary.
            chunk = pop_oldest_until(self.recent, target_tokens=self.window_tokens)
            self.summary = self.summariser(
                current_summary=self.summary,
                new_dialogue=render_messages(chunk),
                instruction="Update summary; preserve constraints, decisions, and open tasks."
            )
```

**Trade-offs**

- Summarisation reduces token cost and can reduce “context poisoning” by omitting known-bad content, as argued in the Agents SDK context-management writeup. citeturn6view0  
- However, abstractive summarisation is vulnerable to hallucination and unfaithfulness; classic summarisation research documents that neural abstractive summarisation models are prone to generating unfaithful content. citeturn4search0  

**Typical hyperparameters**

- `max_token_limit` (hard budget), recent-window size, summarisation trigger condition. citeturn10view0turn6view0  
- Summary style: extractive vs abstractive; structured vs free-form (“facts, constraints, decisions, TODOs”).  
- Update policy: every turn vs milestone-based (see “Hybrid methods” below for why milestone-based often reduces drift). citeturn6view1  

**When to use**

- Conversational agents where coherence matters but raw history becomes too long. citeturn8view0turn10view0  
- Multi-agent pipelines where passing the full transcript between stages is too expensive and summaries serve as inter-stage interfaces. citeturn8view2  

### Chunking and hierarchical memory

**What it compacts**: both tokens and memory store growth, by building multi-resolution representations: raw events → episodes → summaries/themes. citeturn13view2turn1search3turn11search2

**Primary sources and patterns**

- **Virtual-memory-inspired tiers (MemGPT)**: proposes “virtual context management” inspired by hierarchical memory systems that move data between fast and slow tiers, enabling effective context beyond the base model’s limited window. citeturn13view2  
- **Memory stream + reflection (Generative Agents)**: stores a complete record of experiences in natural language, synthesises higher-level reflections over time, and retrieves dynamically for planning and behaviour. citeturn1search3  
- **Hierarchy-driven retrieval for agent memory (xMemory, “Beyond RAG for Agent Memory”)**: argues for decoupling memories into semantic components, organising them hierarchically, and retrieving top-down to reduce redundancy and preserve prerequisite chains. citeturn11search2turn11search6  

**Algorithm sketch: hierarchical consolidation + top-down retrieval**

```python
def build_hierarchy(raw_messages, episode_splitter, summariser, embedder):
    """
    Returns a hierarchy:
      - raw nodes (messages)
      - episode nodes (groups of messages)
      - theme nodes (summaries of episodes)
    """
    episodes = episode_splitter(raw_messages)

    episode_nodes = []
    for ep in episodes:
        ep_summary = summariser("\n".join(m["text"] for m in ep),
                                instruction="Summarise episode; preserve entities, constraints, outcomes.")
        episode_nodes.append({"type": "episode", "summary": ep_summary, "children": ep})

    theme_nodes = []
    clusters = cluster_by_semantics([n["summary"] for n in episode_nodes], embedder)
    for cluster in clusters:
        theme_summary = summariser("\n".join(cluster),
                                   instruction="Create a theme summary that supports later multi-fact queries.")
        theme_nodes.append({"type": "theme", "summary": theme_summary, "children": cluster})

    return {"themes": theme_nodes, "episodes": episode_nodes, "raw": raw_messages}

def retrieve_top_down(query, hierarchy, embedder, k_themes=3, k_episodes=5):
    qv = embedder(query)
    themes = topk_by_embedding(qv, hierarchy["themes"], key="summary", k=k_themes)
    candidate_eps = flatten([t["children"] for t in themes])
    episodes = topk_by_embedding(qv, candidate_eps, key="summary", k=k_episodes)
    # Only expand to raw messages if needed.
    return episodes
```

**Complexity, compute, and storage**

- Building summaries/themes requires additional model calls (or background jobs). LangChain’s memory overview highlights the online vs background trade-off for memory updates (hot path vs asynchronous). citeturn8view0  
- Query-time retrieval can be top-down to limit expansion cost, consistent with the xMemory motivation against naive top‑k redundancy. citeturn11search2  

**Typical hyperparameters**

- Episode segmentation: by time, by topic shift, by tool-run boundary (“milestones”).  
- Cluster granularity: max theme size; similarity threshold; minimum support (avoid brittle micro-themes).  
- Expansion policy: retrieve only summaries unless uncertainty remains (xMemory frames this as “expand when it reduces reader uncertainty”). citeturn11search2  

**When to use**

- Long-term assistants where multi-session reasoning and knowledge updates are required (benchmarks like LoCoMo and LongMemEval stress this). citeturn12search0turn12search1  
- Retrieval-heavy agents where you want small, diverse context “themes” rather than redundant near-duplicates. citeturn11search2  

### Vector-store pruning and merging

**What it compacts**: persistent memory store size (number of vectors/notes) and retrieval-time redundancy.

**Why it matters in agent loops**

The “Beyond RAG for Agent Memory” work emphasises that in dialogue-stream memory, redundancy is a core failure mode: fixed top‑k similarity tends to return near-duplicates; post-hoc pruning can delete prerequisites needed for correct reasoning. citeturn11search2turn11search6

**Algorithm patterns**

1. **Pruning**: remove memories that are stale, low-utility, or dominated by better memories.  
2. **Merging**: combine adjacent or near-duplicate memories into a consolidated memory with provenance links.  
3. **Compaction at the database layer**: deletes may be tombstoned; compaction jobs reclaim space and rebuild indexes (Milvus maintainers note compaction can permanently remove deleted data and can be triggered manually). citeturn5search20  

**Algorithm sketch: usage-aware pruning + similarity merging**

```python
def prune_and_merge(memories, embedder, now_ts,
                    max_items=200_000,
                    ttl_days=180,
                    min_retrievals=2,
                    merge_cosine=0.92):
    """
    memories: list of dicts like:
      {"id": str, "text": str, "embedding": vec, "created": ts,
       "retrieval_count": int, "last_retrieved": ts, "sources": [ref]}
    """
    # 1) TTL pruning (time-based)
    keep = [m for m in memories if (now_ts - m["created"]).days <= ttl_days]

    # 2) Utility pruning (usage-based)
    keep = [m for m in keep if m["retrieval_count"] >= min_retrievals or is_pinned(m)]

    # 3) If still too large, drop least-recently-used
    keep.sort(key=lambda m: (m["last_retrieved"], m["retrieval_count"]))
    keep = keep[-max_items:]

    # 4) Merge near-duplicates using clustering in embedding space
    clusters = cluster_by_cosine([m["embedding"] for m in keep], threshold=merge_cosine)
    merged = []
    for cluster_ids in clusters:
        cluster = [keep[i] for i in cluster_ids]
        merged_text = consolidate_text([m["text"] for m in cluster])
        merged.append({
            "id": new_id(),
            "text": merged_text,
            "embedding": embedder(merged_text),
            "created": min(m["created"] for m in cluster),
            "retrieval_count": sum(m["retrieval_count"] for m in cluster),
            "last_retrieved": max(m["last_retrieved"] for m in cluster),
            "sources": merge_sources(cluster),
        })
    return merged
```

**Trade-offs**

- Aggressive pruning reduces store size and retrieval cost, but can remove rare-but-critical facts; xMemory explicitly warns that pruning can delete prerequisites in an evidence chain. citeturn11search2  
- Merging reduces redundancy but risks “semantic blur” (collapsing distinct events into one vague memory), which can harm temporal reasoning—an ability stressed by LoCoMo and LongMemEval. citeturn12search0turn12search1  

**Hyperparameters**

- TTL windows, maximum store size, merge similarity thresholds, the definition of “pinned” memory.  
- Retrieval `top_k` (and diversification strategies) and re-ranking thresholds (especially in near-duplicate regimes).

**When to use**

- Long-lived personal assistants and customer-service agents where memory growth is unbounded without pruning. citeturn12search1turn11search0  
- Multi-agent systems that share a memory store; without dedup/merge, cross-agent writes can explode store size.

### Knowledge distillation

**What it compacts**: *prompt length* and/or *memory-management logic*, by moving capabilities from context into parameters (or into a smaller auxiliary model).

**Two practical distillation targets**

1. **Distil long instructions/examples into model weights**: OpenAI’s latency optimisation guide explicitly lists fine-tuning as a way to replace lengthy instructions/examples. citeturn7view1  
2. **Distil a compressor model**: LLMLingua’s repository notes that LLMLingua‑2 is trained via data distillation (from GPT‑4) to perform fast token classification for compression. citeturn1search11  

Gisting also frames itself through a “context distillation” perspective, but amortised across tasks: rather than training a new model per prompt, it learns to predict gist representations for unseen prompts. citeturn16view0

**Algorithm sketch: teacher–student compressor distillation**

```python
def distil_compressor(training_prompts, teacher_llm, student_model):
    """
    Train a student model to output compression decisions (keep/drop tokens, or extract key spans).
    """
    for prompt in training_prompts:
        # Teacher provides "important spans" or a compressed prompt (supervision).
        teacher_compressed = teacher_llm(prompt, instruction="Compress while preserving answer-critical info.")
        labels = align_tokens_to_labels(prompt, teacher_compressed)  # token-level keep/drop or span tags
        student_model.train_step(prompt, labels)

    return student_model

def apply_student_compressor(prompt, student_model, budget_tokens):
    scores = student_model.predict_token_scores(prompt)
    selected = select_under_budget(prompt, scores, budget_tokens)
    return selected
```

**Trade-offs**

- Distillation can materially reduce per-turn token budgets and enable stronger caching (more stable prompts), but it introduces model lifecycle management (retraining, drift tracking, evaluation). citeturn7view1turn6view3  
- Distilled compressors can become brittle under domain shift unless trained on diverse prompts resembling production distributions.

**When to use**

- Very high-traffic systems where reducing prompt size yields recurring savings, and you can afford a training/evals pipeline.  
- When stable behaviour matters and you can encode “prompt policy” into weights rather than dynamic prompts.

### Checkpointing and snapshotting

**What it compacts (indirectly)**: not always about size reduction; rather, it enables *controlled compaction* by preserving recoverable ground truth while working context is compressed.

**Framework primitives**

- **LangGraph checkpointers**: persist a checkpoint of graph state at every “super-step” into a thread; supports memory, replay/time travel, and fault tolerance. citeturn9view0turn9view1  
- **Microsoft Agent Framework sessions**: agents are stateless by default; `AgentSession` holds conversation context across invocations and can be serialised/deserialised to persist/rehydrate state. citeturn8view3turn8view4  
- **OpenAI conversation state**: state can be carried by chaining `previous_response_id` or by using a durable conversation object; additionally, a compaction endpoint can produce compacted items for continuation when out of context budget. citeturn6view2turn19view2turn19view0  

**Algorithm sketch: milestone snapshots with reproducible resumes**

```python
class CheckpointManager:
    def __init__(self, store):
        self.store = store

    def checkpoint(self, run_id, step_id, state_obj):
        snap = serialize(state_obj)  # JSON, msgpack, etc.
        self.store.put(f"{run_id}:{step_id}", snap)

    def restore(self, run_id, step_id):
        return deserialize(self.store.get(f"{run_id}:{step_id}"))

def should_checkpoint(step):
    return step.is_tool_heavy or step.is_milestone or step.step_index % 10 == 0
```

**Costs and tuning**

- Storage grows with snapshot frequency and state size; you typically snapshot heavier (milestone) states and store deltas between them (next section).  
- The benefit is debugging and safety: when lossy compaction causes a failure, you can replay from a prior snapshot and change compaction thresholds/policies.

### Delta encoding

**What it compacts**: storage of state/memory changes *between* checkpoints; can also apply to KV caches.

**Primary sources in LLM serving**

- CacheGen explicitly studies locality across tokens and contrasts “delta values”; it builds encoding schemes (quantisation + arithmetic coding) leveraging these distributional properties to compress KV caches into bitstreams. citeturn18view0  
- DeltaKV proposes residual-based KV-cache compression using long-range similarity and shared latent components, encoding residuals relative to retrieved historical references rather than discarding tokens. citeturn5search0turn17view0  

**Algorithm sketch: delta-log + periodic base snapshot**

```python
def delta_encode(prev_state, next_state):
    """
    Return patch operations that transform prev_state into next_state.
    In practice, use JSON-patch-like ops or typed diffs.
    """
    return compute_structured_diff(prev_state, next_state)

def apply_delta(state, delta):
    return apply_structured_diff(state, delta)

class DeltaCheckpoint:
    def __init__(self, base_every=50):
        self.base_every = base_every
        self.bases = {}   # step -> state
        self.deltas = {}  # step -> delta from previous step

    def record(self, step, state):
        if step % self.base_every == 0:
            self.bases[step] = state
        else:
            prev = self.get(step - 1)
            self.deltas[step] = delta_encode(prev, state)

    def get(self, step):
        base_step = max(s for s in self.bases if s <= step)
        state = self.bases[base_step]
        for s in range(base_step + 1, step + 1):
            state = apply_delta(state, self.deltas[s])
        return state
```

**Trade-offs**

- Delta encoding is best when state changes are sparse or structured (e.g., small updates to a plan, a few new memory items).  
- For high-entropy changes (large tool outputs that change completely), deltas can be as large as full snapshots; in those regimes, alternatives include storing external artefacts and only keeping references/hashes in state.

### Lossy vs lossless approaches

A practical taxonomy for agent loops:

- **Lossless (exact)**
  - Prompt prefix caching (reuses previously computed prefix work; requires exact prefix matches and stable ordering). citeturn6view3turn7view1  
  - Checkpointing and replay/time travel for state. citeturn9view0turn8view4  
  - Some KV-cache encoding schemes can be configured for minimal or “no additional loss” trade-offs; CacheGen explicitly describes loss-aware compression levels and can fall back to recomputation. citeturn18view0  

- **Lossy (approximate)**
  - Summarisation of history (running summaries, milestone summaries). citeturn10view0turn6view0  
  - Token dropping / learned prompt compression. citeturn15view0turn16view0  
  - Vector-store merging and aggressive pruning. citeturn11search2turn13view5  

In agent engineering, lossless methods are most valuable for **auditability and recovery**, while lossy methods are most valuable for **day-to-day efficiency**; robust systems generally combine them.

### Hybrid methods

Hybrid designs dominate in mature agent stacks because different bottlenecks require different compaction tools.

**A reference hybrid pipeline**

1. **Stable prefix + caching**: keep system instructions and tool schemas stable and early; push dynamic context later for cache friendliness. citeturn6view3turn7view1  
2. **Short-term management**: trim older turns; summarise tool-heavy phases; keep a recent raw window. citeturn6view0turn10view0turn8view0  
3. **Long-term store**: extract “facts/decisions/preferences”, store in a retrievable store, prune/dedup periodically; retrieve diverse themes rather than redundant top‑k. citeturn8view0turn11search2turn13view5  
4. **Milestone compaction for continuation**: in OpenAI’s GPT‑5.2 guidance, compaction is recommended after major milestones (tool-heavy phases) rather than every turn; compacted items are treated as opaque. citeturn6view1turn19view2  
5. **Checkpointing**: persist state to permit replay and controlled debugging. citeturn9view0turn8view4  

```mermaid
flowchart TB
  subgraph OnlineLoop[Online agent loop]
    P[Prompt Builder\n(stable prefix + dynamic tail)] --> L[LLM step]
    L --> T[Tools / Environment]
    T --> S[State Update]
    S --> P
  end

  subgraph Memory[Memory subsystem]
    E[Extract facts/decisions] --> V[(Vector/Graph store)]
    V --> D[Dedup + prune + merge]
    D --> V
  end

  S --> E
  V --> P

  subgraph Continuity[Continuity & recovery]
    CP[Checkpoints / sessions] --> R[Replay / Resume]
    C[Compaction endpoint\n(opaque items)] --> P
  end

  S --> CP
  L --> C
```

## Failure modes and risks

### Information loss and prerequisite deletion

In dialogue-stream memory, aggressive pruning can remove information that is not redundant but *structurally necessary* for multi-step reasoning. The “Beyond RAG for Agent Memory” paper explicitly warns that pruning can delete “prerequisites within an evidence chain,” and that fixed similarity top‑k can return redundant context, motivating hierarchy-based retrieval rather than simple pruning. citeturn11search2turn11search6

### Semantic drift from repeated summarisation

Repeated progressive summarisation (summary-of-summary) can gradually drift away from the original intent, especially when the summariser is abstractive. This risk is amplified because summarisation systems are prone to unfaithful generation; classic summarisation research documents hallucinations/unfaithfulness as a common failure mode. citeturn4search0turn10view0

### Hallucination and “compacted truth” becoming authoritative

A particularly dangerous pattern is when a hallucinated summary becomes the *only* surviving representation after compaction; the agent may then treat the hallucination as ground truth and propagate it across turns.

Mitigations include:
- Preserve provenance pointers (IDs/hashes) so the system can fetch raw sources when needed.  
- Keep “hard constraints” (user preferences, policies, tool schemas) in structured state, not only in summaries. citeturn8view0turn6view0  

### Consistency, conflict resolution, and knowledge updates

Benchmarks for agent memory increasingly emphasise *knowledge updates* (new info superseding old) and *abstention* (recognising missing info). These are exactly where naive compaction can fail (e.g., merging old and new into an ambiguous memory). LongMemEval explicitly targets knowledge updates and abstention as core long-term memory abilities. citeturn12search1

### Silent truncation and context overflows

If an API truncates context automatically, the “oldest” conversation items can be dropped to fit the context window—this is a form of implicit compaction that can be hard to notice. The Responses API reference documents that with truncation set to `auto`, items may be dropped from the beginning of the conversation to fit within the context window. citeturn7view2

### Debugging difficulty and reduced inspectability

Lossy compaction makes debugging harder because reproduction requires the exact compaction outcome. Framework checkpointing features (e.g., LangGraph threads/checkpoints with replay and state history) exist largely to mitigate this operational risk. citeturn9view0turn9view1

A special case is **opaque compaction**: OpenAI’s `/responses/compact` returns encrypted, opaque items and notes that underlying logic may evolve; this improves portability and can preserve task-relevant information with reduced token footprint, but reduces inspectability and therefore shifts trust toward testing and instrumentation. citeturn19view2turn6view1

## Evaluation metrics and benchmarking methodology

A rigorous evaluation should treat compaction as a *system component* with measurable trade-offs, not a qualitative “it seems shorter” tweak.

### Metrics

**End-to-end task performance**
- Accuracy / task success rate on agent tasks.  
- Error categories: missing constraints, wrong tool calls, contradictory decisions.

**Memory and retrieval**
- Recall@k / context recall for whether necessary memories are retrieved (LongMemEval and related work commonly use retrieval recall + judged answer accuracy). citeturn12search1turn12search11  
- Conflict resolution and selective forgetting competence (MemoryAgentBench frames memory-agent evaluation around competencies including accurate retrieval and conflict handling). citeturn11search17turn11search13  

**Semantic fidelity of compaction**
- Faithfulness/grounding measures for whether the compressed representation supports the same answers as the original (RAGAs provides reference-free metrics for RAG quality, including faithfulness and relevancy). citeturn5search2turn5search6  
- For summaries, consider factual consistency checks and targeted QA over the original vs compressed state, motivated by the summarisation faithfulness literature. citeturn4search0  

**Efficiency**
- Latency: TTFT and p50/p95 per-turn latency. (Mem0 reports p95 latency improvements and large token savings relative to full-context baselines.) citeturn11search0  
- Token cost: input tokens per turn; number of model calls; number of tool calls.  
- Memory footprint:
  - Persistent store size (#items, bytes, index size).  
  - Inference memory: KV cache size/ratios; CacheGen and DeltaKV report KV-cache size reductions and efficiency ratios. citeturn18view0turn17view0  

### Benchmark choices

- **LoCoMo**: very long multi-session conversations (hundreds of turns), designed to measure long-term conversational memory and temporal reasoning. citeturn12search0  
- **LongMemEval**: evaluates long-term interactive memory across multiple abilities including knowledge updates and abstention. citeturn12search1turn12search5  
- **MemoryAgentBench**: explicitly targets incremental, multi-turn memory-agent evaluation across competencies (accurate retrieval, test-time learning, long-range understanding, conflict resolution). citeturn11search17turn11search13  
- **PerLTQA**: personal long-term memory QA with different memory types, useful for testing persona/episodic memory handling. citeturn12search2turn12search23  

A recommended methodology is to evaluate (a) a no-compaction baseline, (b) a simple trim+summary baseline, (c) a retrieval baseline, and then (d) advanced compressors, using identical prompts and tooling where possible to isolate compaction effects.

## Framework implementations and case studies

### entity["company","LangChain","llm framework company"] and entity["organization","LangGraph","agent orchestration library"]

LangChain’s memory guidance distinguishes **short-term** (thread-scoped) memory stored as part of agent state and persisted via a checkpointer, versus **long-term** memory stored across sessions/threads (namespaced stores). It also explicitly warns that long conversations can exceed context windows and that models may perform poorly over long contexts, motivating trimming and forgetting strategies. citeturn8view0turn9view0turn8view1

LangGraph operationalises persistence via **checkpointers**: when configured, the checkpointer saves graph state at every super-step to a thread, enabling memory, time travel, and fault tolerance. citeturn9view0turn9view1

A representative “semantic summarisation” pattern in the LangChain ecosystem is `ConversationSummaryBufferMemory`, which maintains a rolling summary plus recent messages under a `max_token_limit`. citeturn10view0turn10view1

### entity["organization","AutoGen","multi-agent conversation framework"]

AutoGen provides explicit multi-agent conversation patterns and includes built-in **chat summarisation**. The conversation patterns documentation describes how a chat history is summarised after termination; sequential chat uses “carryover” that accumulates summaries across stages; and `summary_method` can be set to strategies including LLM-based “reflection_with_llm,” with a default of using the last message as the summary. citeturn8view2

Operationally, this is a canonical example of compaction as an *inter-agent interface*: summaries become the compressed contract passed between agent stages.

### entity["organization","Microsoft Agent Framework","agent runtime library"]

Microsoft’s Agent Framework migration documentation emphasises that agents are stateless by default; to preserve conversation state, developers use an `AgentSession` that can be reused across calls (and serialised/deserialised for persistence). citeturn8view3turn8view4

This maps directly to the “state compaction + checkpointing” view: the session is the serialised state object; compaction strategies sit on top (history providers, trimming, storage policies).

### entity["company","OpenAI","ai company, us"] best practices and APIs

OpenAI’s conversation-state guidance describes multiple approaches: manually managing message history, chaining with `previous_response_id`, or using durable conversation objects. citeturn6view2turn7view2

For efficiency, OpenAI provides:
- **Prompt caching**: cache hits require exact prefix matches; caching activates above a prompt-length threshold and includes guidance on structuring prompts (static-first, dynamic-last) and retention windows. citeturn6view3  
- **Latency optimisation guidance** explicitly calls out fine-tuning to replace lengthy instructions, filtering context inputs, and maximising shared prompt prefixes to be more KV-cache friendly. citeturn7view1  
- **Compaction endpoint** `/responses/compact`: runs a compaction pass and returns encrypted, opaque items; the API reference cautions that underlying logic may evolve, and recommends use when running out of tokens. citeturn19view2turn6view1  
- **Agents SDK context management**: the Sessions cookbook focuses on trimming and compression for long-running interactions, framing them as key to reliability, tool-call accuracy, latency/cost reduction, and debuggability. citeturn6view0  

### entity["company","Microsoft","technology company"] entity["organization","DeepSpeed","deep learning optimisation library"] and KV-cache/offload systems

Although memory compaction is often discussed at the prompt/memory level, serving systems tackle *model-internal* state growth:

- **ZeRO-Inference** discusses offloading model weights and optimising throughput-oriented inference when models exceed GPU memory; it reports throughput comparisons under full vs partial offload and explores prefetching effects. citeturn8view5turn3search6  
- DeepSpeed’s ZeRO-Inference examples emphasise combined optimisations (weight quantisation + KV cache offloading) for large throughput improvements in inference. citeturn3search2  

These are not “agent memory” features per se, but they become critical when agents do long-context multi-turn reasoning, because per-turn inference state (KV cache, prefill) dominates latency and cost. citeturn17view0turn18view0

### entity["organization","vLLM","llm inference engine"] and KV-cache memory management

PagedAttention/vLLM is a canonical “serving-state compaction” approach: KV cache memory per request is huge and dynamic; inefficient management wastes memory via fragmentation; PagedAttention uses paging techniques inspired by virtual memory to reduce KV-cache waste and improve throughput. citeturn3search1turn3search5

### Academic systems and recent case studies

Several research systems connect directly to compaction in agent loops:

- **MemGPT**: hierarchical memory tiers and interrupts for virtual context management across long document analysis and multi-session chat. citeturn13view2  
- **Generative Agents**: memory stream + reflections + retrieval to support long-horizon coherent behaviour. citeturn1search3  
- **Mem0**: memory-centric architecture that extracts, consolidates, and retrieves salient conversational information; reports substantial token savings and lower p95 latency versus full-context approaches, while improving evaluated memory performance on LoCoMo categories. citeturn11search0turn12search0  
- **A‑MEM**: Zettelkasten-inspired atomic notes with dynamic linking and memory evolution (updating prior memories as new ones arrive). citeturn13view5  
- **AgeMem**: unifies long-term and short-term memory operations as tool actions (Add/Update/Delete + Retrieve/Summary/Filter), learning a memory policy; the paper notes typical `k` values (3–5) for retrieval to balance relevance and context size. citeturn13view4  
- **xMemory** (“Beyond RAG for Agent Memory”): proposes hierarchy-driven decoupling and aggregation; retrieves compact, diverse themes and expands only when needed, reporting gains in answer quality and token efficiency on LoCoMo and PerLTQA. citeturn11search2turn12search2turn12search0  

## Comparative analysis and decision matrix

### Technique comparison

The table below is intentionally qualitative; exact numbers depend on model, context distributions, and evaluation harness.

| Technique | Primary target | Typical efficiency gain | Fidelity risk | Extra compute | Storage implications | Most suitable scenarios |
|---|---|---|---|---|---|---|
| Prompt prefix caching | Prompt compute reuse | Often large when prefixes repeat | Low (lossless) | Low (automatic) | None for app (provider-managed) | High-volume agents with stable system prompts citeturn6view3turn7view1 |
| Token-level prompt compression (LLMLingua-style) | Prompt tokens | High (multi‑× token reduction) | Medium (drops tokens) | Medium (compressor passes) | Minimal | Long prompts where redundancy is high, APIs-only target models citeturn15view0 |
| Gist tokens | Prompt tokens + cached activations | High (up to ~26× in paper) | Medium (learned compression) | Training required | Cache gist activations | Reused prompts/tasks with many queries; when you can use gist-trained models citeturn16view0 |
| Rolling summaries + recent window | Prompt tokens | Medium to high | Medium to high (hallucination/drift) | Medium (summary calls) | Store summaries + raw window | Conversational continuity without full history citeturn10view0turn4search0 |
| Hierarchical memory (episodes/themes) | Prompt + long-term memory | High | Medium (depends on expansion policy) | Medium to high | More metadata/hierarchy | Long-horizon agents; multi-fact queries; duplication-heavy memory streams citeturn11search2turn13view2turn1search3 |
| Vector-store prune/merge | Long-term store | Medium | Medium (prerequisite loss) | Medium (periodic jobs) | Reduces store size | Persistent assistants; multi-agent shared memory citeturn11search2turn13view5 |
| Checkpointing + replay | Explicit state robustness | Indirect (enables safe lossy compaction) | Low | Low to medium | Increases storage | Production agents needing auditability and recovery citeturn9view0turn8view4 |
| Delta encoding | Explicit state / KV cache | Medium to high when deltas sparse | Low–medium | Medium | Reduces storage for history | Tool-heavy agents; KV-cache streaming/compression stacks citeturn18view0turn17view0 |
| KV-cache compression/encoding (CacheGen/DeltaKV) | Serving internal caches | High for long contexts | Low–medium (loss-aware) | Medium–high | Reduces bandwidth/memory | Long-context inference, multi-turn sessions, distributed serving citeturn18view0turn17view0 |
| Opaque compaction endpoint | Conversation state size | High token footprint reduction | Medium (less inspectable) | Low (endpoint call) | Store opaque items | When hitting context limits and needing continuation; milestone compaction citeturn19view2turn6view1 |

### Decision matrix by use-case

| Use-case | Primary bottleneck | Recommended compaction stack | Notes |
|---|---|---|---|
| Conversational agents (single-agent chat) | Token growth + coherence | Stable system prefix + prompt caching; rolling summary + recent window; checkpoint sessions | Summaries must be factual; keep raw “recent window” to reduce drift. citeturn6view3turn10view0turn8view4turn4search0 |
| Long-term memory agents (multi-session personal assistant) | Memory growth + updates | Hierarchical memory (episodes/themes); vector-store prune/merge; knowledge-update policy (new overrides old); benchmark on LongMemEval/LoCoMo | Optimise for temporal reasoning and knowledge updates; avoid over-merging. citeturn11search2turn12search1turn12search0 |
| RAG / retrieval-augmented agents | Retrieval redundancy + “distractors” | Retrieval diversification; compress retrieved evidence; evaluate with RAGAs; consider hierarchy-based retrieval for agent memory streams | In bounded memory streams, naive top‑k may be mostly duplicates. citeturn11search2turn5search2turn5search6 |
| Multi-agent systems | Cross-agent context explosion + inconsistency | Summarised carryover contracts between agents; shared memory store with dedup/prune; checkpoint each agent’s state for reproducibility | AutoGen-style “carryover” is a standard pattern; ensure provenance to recover from summary errors. citeturn8view2turn9view0turn11search2 |
| Tool-heavy planning/execution agents | Tool logs dominate context | Milestone-based summarisation of tool phases; structured state + delta logs; compaction endpoint as escape hatch; maximise shared prefix | OpenAI guidance: compact after milestones, not every turn; keep prompts functionally identical when resuming. citeturn6view1turn19view2turn6view0 |
| Long-context inference (serving focus) | KV cache memory/TTFT | KV-cache streaming/encoding (CacheGen); residual/delta approaches (DeltaKV); paging allocation (PagedAttention) | Serving-state compaction can dominate user-visible latency in long contexts. citeturn18view0turn17view0turn3search1 |

### A practical selection procedure

1. **Identify the bottleneck**: tokens per turn, retrieval redundancy, p95 latency, TTFT, GPU memory, or persistent store growth. (Mem0 and CacheGen provide empirical examples of latency/token savings from memory/context engineering and KV handling.) citeturn11search0turn18view0  
2. **Choose the highest-fidelity lever first**: prompt caching + stable prefixes, structured state externalisation, checkpointing. citeturn6view3turn9view0  
3. **Introduce lossy methods gradually**: summarisation, token dropping, merging—always paired with a recovery path (raw logs, provenance, checkpoints). citeturn4search0turn9view0turn11search2  
4. **Validate on memory benchmarks** relevant to your agent’s behaviour (LoCoMo/LongMemEval/MemoryAgentBench/PerLTQA). citeturn12search0turn12search1turn11search17turn12search2  
5. **Treat compaction as a model change**: run regression evals whenever you change compaction policy, summary prompts, thresholds, or retrieval rules (OpenAI’s guidance repeatedly emphasises stable prompts and evaluating changes). citeturn6view1turn7view1