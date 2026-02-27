# LLM as Task Compiler  
## A Cost-Aware Execution Architecture for General-Purpose Agents

### Executive Summary

General-purpose LLM agents frequently overuse context windows for batch or compliance-heavy tasks, resulting in high token costs and unreliable constraint handling. This document proposes a pragmatic architectural shift: treat the LLM as a semantic planner that compiles large or structured tasks into deterministic execution pipelines when economic or reliability thresholds are exceeded.

---

## 1. The Core Insight

Not all tasks should be executed in-prompt.

Tasks that involve:

- Batch processing (N ≥ 10 items),
- Ranking or scoring,
- Compliance guarantees (e.g., include links),
- Auditability requirements,
- External data sources,

should trigger programmatic execution.

---

## 2. Execution Modes

### Prompt Mode
Small tasks, low risk.

### Retrieval Mode
Iterative narrowing with moderate complexity.

### Compiled Task Mode
LLM generates:
- Rubric
- Extraction schema
- Validation rules

Runtime executes:
- Data retrieval
- Normalization
- Deterministic scoring
- Constraint enforcement
- Report rendering

---

## 3. Cost Model

Estimated in-prompt cost:
