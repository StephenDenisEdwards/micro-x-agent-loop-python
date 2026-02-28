# Cost-Aware Task Compilation for Large Language Model Agents  
## Separating Semantic Reasoning from Deterministic Execution

### Abstract

Large Language Model (LLM) agents are increasingly deployed for complex, multi-step tasks involving external data retrieval, structured evaluation, and compliance-sensitive output generation. While contemporary systems expand context windows and integrate retrieval mechanisms, many real-world workloads remain economically inefficient and reliability-fragile when executed purely within prompt space. This paper argues that the limitation is not primarily one of memory capacity but of architectural role assignment. We propose a cost-aware task compilation framework in which the LLM acts as a semantic planner that compiles structured tasks into deterministic execution pipelines when batch size, compliance constraints, or economic thresholds exceed safe in-context processing bounds. By separating semantic reasoning from deterministic execution, agents achieve improved cost efficiency, stronger constraint guarantees, and enhanced scalability. This work formalizes execution modality switching as an executive layer in LLM agents and reframes the model’s role within hybrid computational systems.

---

## 1. Introduction

Large Language Models have demonstrated remarkable capability in semantic reasoning, abstraction, and generative tasks. As these models are embedded within agent systems, they are increasingly asked to perform structured, multi-step workloads that extend beyond conversational interaction. Examples include ranking job postings against a rubric, triaging support tickets, screening resumes, analyzing log batches, or generating audit-ready reports from structured data sources.

Despite expanded context windows and retrieval augmentation, such workloads expose a structural limitation: executing large batch or compliance-sensitive tasks entirely within prompt space is both economically inefficient and reliability-fragile. Token cost scales with raw data volume, attention mechanisms dilute instruction salience as sequence length increases, and constraint enforcement remains probabilistic rather than deterministic.

This paper proposes that the solution is not simply larger context windows, but architectural separation. The LLM should not be treated as the execution engine for deterministic batch processing. Instead, it should function as a semantic task compiler that delegates structured execution to an external runtime when economic or reliability thresholds are exceeded.

---

## 2. The Prompt-Centric Execution Limitation

Transformer architectures process input sequences using attention mechanisms whose computational and memory costs grow superlinearly with context length. While practical implementations mitigate worst-case scaling, large contexts remain computationally expensive and economically significant. More importantly, context expansion does not convert probabilistic reasoning into deterministic constraint enforcement.

Consider a representative workload: evaluating N items against a rubric and producing a ranked report with mandatory inclusion of specific fields (e.g., hyperlinks). Executed naïvely in prompt space, the full content of all items must be injected into context, increasing token cost proportionally to N. The model must simultaneously maintain constraint salience, perform ranking, and generate structured output within a single generative trajectory.

Two systemic issues arise:

1. **Economic inefficiency:**  
   Token cost grows linearly with data volume, while attention cost grows superlinearly. For sufficiently large N, the majority of inference cost is consumed by raw data payload rather than reasoning.

2. **Constraint fragility:**  
   Requirements such as “include one link per item” are enforced probabilistically. Even large models occasionally omit low-salience constraints in long contexts.

These limitations are architectural, not purely cognitive.

---

## 3. The Executive Control Gap

LLMs optimize next-token likelihood conditioned on context. They do not natively instantiate persistent task objects, long-horizon goal tracking, or deterministic validation mechanisms. While they can represent plans in text, they do not internally maintain structured state across execution steps.

In contrast, robust execution of structured workloads requires:

- Persistent memory of task constraints,
- Deterministic scoring or ranking logic,
- Exact item count enforcement,
- Guaranteed inclusion of mandatory fields,
- Reproducible results.

When these responsibilities are placed entirely within prompt space, the model must simulate executive control through probabilistic text generation. This simulation degrades as workload size increases.

The gap between semantic simulation and deterministic instantiation becomes the limiting factor.

---

## 4. Cost-Aware Task Compilation

We propose a hybrid architecture in which the agent dynamically selects between execution modalities based on economic and structural criteria.

### 4.1 Execution Modalities

Three execution modalities are defined:

- **Prompt Mode:** All reasoning occurs within context. Suitable for small, low-risk tasks.
- **Retrieval Mode:** Iterative retrieval reduces context footprint while reasoning remains LLM-driven.
- **Compiled Task Mode:** The LLM generates a structured task specification, and deterministic execution is performed externally.

Compiled Task Mode is activated when:

- Batch size exceeds threshold,
- Deterministic ranking or scoring is required,
- Compliance constraints are strict,
- Estimated prompt-mode cost exceeds economic threshold.

---

### 4.2 Cost Model

Let:

C_prompt ≈ B + N × T_item + T_reason + T_output

Where B is base instruction cost, N is item count, and T_item is average token size per item.

Let:

C_program ≈ T_rubric + N × T_extract + T_report

Where T_rubric represents rubric interpretation cost and T_extract represents compact feature extraction cost.

When:

(C_prompt / C_program) > k

or when reliability constraints are present, execution switches to Compiled Task Mode.

This formalizes execution strategy selection as an economic decision rather than a heuristic preference.

---

## 5. Separation of Roles

In Compiled Task Mode, responsibilities are divided:

The LLM performs:
- Rubric interpretation,
- Schema design,
- Feature extraction guidance,
- Narrative synthesis.

The runtime performs:
- Data retrieval,
- Normalization into compact structured records,
- Deterministic scoring and sorting,
- Constraint validation,
- Artifact generation.

This separation transforms deterministic operations into code-level guarantees and reserves semantic reasoning for the model.

---

## 6. Deterministic Constraint Enforcement

Compiled execution enables guarantees not achievable reliably in prompt-only execution:

- Exact N enforcement,
- Mandatory field validation,
- Reproducible ranking,
- Structured output conformance,
- Targeted repair loops for missing data.

Constraint compliance becomes a property of runtime logic rather than token probability distribution.

---

## 7. Theoretical Framing

This architecture clarifies a distinction between representation and instantiation.

LLMs can represent plans, control structures, and validation logic in text. However, representation does not equate to persistent execution. By externalizing deterministic components, the agent instantiates executive control through runtime structure rather than relying on probabilistic simulation.

Furthermore, the proposal addresses an objective-function mismatch. LLMs optimize token likelihood, while agents must optimize:

- Goal completion,
- Economic efficiency,
- Constraint reliability.

Cost-aware modality switching introduces a meta-objective layer that aligns execution strategy with these goals.

---

## 8. Evaluation Criteria

The effectiveness of cost-aware task compilation can be evaluated using:

- Percentage reduction in token consumption,
- Constraint compliance rate,
- Reproducibility of ranking outputs,
- Latency comparison,
- Economic break-even thresholds,
- Failure rate under increasing batch size.

Such metrics enable empirical comparison between prompt-only and compiled-task execution.

---

## 9. Limitations and Trade-offs

The approach introduces complexity:

- Mode misclassification may increase latency.
- Code generation requires sandboxing.
- DSL design may introduce brittleness.
- System architecture becomes more layered.
- **MCP protocol constraint:** MCP servers return unstructured text content blocks by specification. Generated programs cannot assume structured (JSON) inputs from MCP tool calls, which limits deterministic programmatic processing. This may require per-item LLM interpretation within the compiled pipeline, changing the cost model from "zero LLM cost for execution" to "N small LLM calls." See [ADR-014](../../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md).

However, these are engineering trade-offs rather than conceptual weaknesses.

---

## 10. Conclusion

Expanding context windows alone does not resolve economic inefficiency or reliability fragility in structured agent workloads. By separating semantic reasoning from deterministic execution and introducing cost-aware execution modality switching, LLM agents can achieve improved scalability, stronger compliance guarantees, and predictable economic performance.

This reframes the role of the LLM within agent systems: not as the universal execution engine, but as a semantic planner embedded within a hybrid computational architecture.

Cost-aware task compilation represents a practical step toward robust, economically sustainable AI agent systems.