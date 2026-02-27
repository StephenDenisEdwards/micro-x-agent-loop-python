# LLM as Task Compiler  
## A Cost-Aware Execution Architecture for General-Purpose Agents

### Executive Summary

General-purpose LLM agents frequently attempt to solve large, structured, or compliance-sensitive tasks entirely within a single prompt context. While this approach works for small, conversational tasks, it becomes economically inefficient and reliability-fragile as task size and structural constraints increase.

This paper proposes a practical architectural shift: treat the LLM not as the execution engine, but as a **semantic task compiler**. When task characteristics indicate high token cost, deterministic requirements, or compliance sensitivity, the agent should switch from prompt-based reasoning to programmatic execution. The LLM generates task specifications, rubrics, and extraction logic; a runtime executes deterministic processing; and the LLM returns only to produce narrative output from compact, structured results.

This separation of semantic reasoning from deterministic execution enables lower token cost, stronger reliability guarantees, and improved scalability in real-world agent systems.

---

## 1. The Limitation of Prompt-Centric Execution

Modern LLM systems advertise large context windows, but context expansion does not eliminate fundamental economic and architectural constraints. Transformer attention scales quadratically with sequence length, increasing computational cost and latency. More importantly, large prompts dilute instruction salience and leave constraint compliance probabilistic rather than guaranteed.

Consider a task such as ranking 20 job postings against a rubric and producing a structured report that includes mandatory application links. Executed naïvely in prompt space, this task requires injecting all job content into context, reasoning over it, and generating structured output. Token cost grows linearly with data size while attention cost grows superlinearly. Compliance constraints such as “include a link for each job” remain vulnerable to omission.

In practice, expanding context windows postpones but does not solve these problems. The limitation is not merely memory size; it is architectural.

---

## 2. The Executive Control Gap

LLMs simulate reasoning effectively, but they do not instantiate persistent executive control. They optimize next-token likelihood rather than goal completion under constraints. They do not natively maintain durable task objects, audit compliance deterministically, or optimize for economic efficiency across multi-step execution.

This becomes operationally significant in structured batch tasks. Without an external executive layer, the model must:

- Hold all working data in prompt space.
- Track constraints probabilistically.
- Perform ranking and validation within a single forward pass.
- Risk forgetting low-salience requirements.

The result is cost inflation and reliability drift.

---

## 3. The Core Insight

Not all tasks should be executed in prompt space.

Tasks involving large batches, deterministic scoring, mandatory field enforcement, reproducibility requirements, or external data retrieval are structurally better suited to programmatic execution. In these cases, the LLM should act as a semantic planner that compiles the task into an executable pipeline.

This approach introduces three execution modalities:

- **Prompt Mode** for small, low-risk tasks.
- **Retrieval Mode** for moderately scoped tasks requiring iterative narrowing.
- **Compiled Task Mode** for large, structured, or compliance-sensitive workloads.

The innovation is not the use of code itself, but the deliberate, cost-aware switching between modalities.

---

## 4. Cost-Aware Modality Switching

Execution mode selection can be guided by a simple cost model.

Estimated prompt-mode cost:

C_prompt ≈ B + N × T_item + T_reason + T_output

Where:
- B is base instruction cost,
- N is item count,
- T_item is average tokens per item,
- T_reason is reasoning overhead,
- T_output is report length.

Estimated compiled-mode cost:

C_program ≈ T_rubric + N × T_extract + T_report

If C_prompt significantly exceeds C_program, or if reliability constraints are present, the system should switch to Compiled Task Mode.

This transforms economic efficiency from an incidental property into an explicit architectural decision.

---

## 5. Compiled Task Mode Architecture

In Compiled Task Mode, responsibilities are separated:

**The LLM generates:**
- A structured task specification.
- A rubric interpretation.
- A normalized extraction schema.
- Validation rules.
- A report template.

**The runtime executes:**
- Data acquisition from external sources.
- Field extraction and normalization.
- Deterministic scoring and sorting.
- Constraint validation (e.g., link inclusion).
- Artifact generation.

**The LLM returns to:**
- Produce a concise narrative summary using compact, structured data.

The LLM no longer carries the entire working set in context. Deterministic logic moves outside token space.

---

## 6. Deterministic Guarantees

Compiled Task Mode enables guarantees that prompt-only execution cannot reliably provide:

- Exact item counts.
- Mandatory field enforcement.
- Link inclusion validation.
- Reproducible ranking.
- Structured output conformance.

Constraint satisfaction becomes deterministic rather than probabilistic.

---

## 7. Practical Benefits

This architecture provides:

- Significant token cost reduction.
- Reduced hallucination probability.
- Improved compliance reliability.
- Better economic predictability.
- Clear separation of concerns.
- Enterprise-ready execution guarantees.

It mirrors the pattern already visible in robust systems such as code interpreters and coding agents, which externalize deterministic execution to compilers, runtimes, or test suites.

---

## 8. Risks and Trade-Offs

This approach introduces trade-offs:

- Over-triggering compiled mode may increase latency.
- Code execution must be sandboxed.
- DSL design may introduce brittleness.
- System complexity increases.
- Mode selection policy must remain simple and deterministic.

However, these risks are engineering challenges, not conceptual flaws.

---

## 9. Strategic Implications

Future LLM agents should not rely solely on larger context windows. Instead, they should orchestrate multiple computational substrates and dynamically select execution strategies based on cost, structure, and reliability requirements.

This reframes the LLM as a semantic planner embedded within a broader executive compute system.

Intelligence remains in semantic interpretation and narrative generation. Determinism, state persistence, and constraint enforcement belong in runtime.

---

## 10. Conclusion

Expanding context windows does not resolve economic and reliability constraints in structured agent tasks. By separating semantic reasoning from deterministic execution and introducing cost-aware modality switching, general-purpose agents can achieve greater scalability, stronger compliance guarantees, and predictable economic performance.

The LLM becomes not the execution engine, but the compiler of task-specific computation.

This shift represents a practical step toward robust, economically sustainable AI agent systems.