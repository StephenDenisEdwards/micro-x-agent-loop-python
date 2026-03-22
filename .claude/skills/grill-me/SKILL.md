---
name: grill-me
description: "Use when the user wants to be interviewed about a plan, design, or feature to surface assumptions, resolve ambiguities, and reach shared understanding before implementation. Triggered by 'grill me', 'interrogate this plan', 'poke holes', or 'challenge this design'."
---

# Grill Me

Relentlessly interview the user about every aspect of their plan until you reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one.

*Core principle:* Never ask a question you can answer by exploring the codebase or documentation. Your job is to surface assumptions, ambiguities, and contradictions — not to waste the user's time on things you can look up.

## Scope

If `$ARGUMENTS` contains `quick` — limit to the 3-5 most foundational branches only. Default is full depth.

## Process

1. **Read the plan** — Load the full plan/spec/design document the user points you to.
2. **Read relevant docs** — Check ADRs, design docs, and planning docs in `documentation/docs/` for prior decisions that constrain or inform this plan. Note any conflicts. ADRs are especially important: they record *why* decisions were made, not just *what*.
3. **Explore the codebase** — Before asking anything, investigate relevant code, schemas, patterns, and conventions. Answer your own questions first.
4. **Build the decision tree** — Identify every decision point, assumption, and dependency in the plan.
5. **Grill branch by branch** — For each branch:
   - State what you understand
   - State what you found in the codebase and docs that's relevant
   - When something is ambiguous, propose a default based on existing patterns ("I'd assume X based on Y — does that hold?") and let the user push back, rather than asking open-ended questions
   - Ask pointed questions about gaps, ambiguities, or conflicts
   - Don't move on until the branch is resolved
6. **Surface dependencies** — When one decision affects another, call it out and resolve them in dependency order.
7. **Summarize** — After all branches are resolved, present a numbered **decision log** (decision + rationale) as the implementation spec. This is the artifact — it should be concrete enough that an implementer can pick it up with zero ambiguous decisions.

## Rules

- **One branch at a time.** Don't shotgun 10 questions. Pick the most foundational unresolved branch and drill into it.
- **Codebase and docs first.** If a question can be answered by reading code, config, schema, existing patterns, ADRs, or design docs — do that instead of asking. If the plan contradicts an ADR, surface it explicitly: "ADR-NNN decided X for reason Y — your plan assumes Z. Is this intentionally revisiting that decision?"
- **Be specific.** "How should this work?" is weak. "The plan says X, but the current code does Y — which should win?" is strong.
- **Challenge assumptions.** If something seems underspecified, contradictory, or overly optimistic — say so directly.
- **Don't accept hand-waves.** If the plan says "we'll figure out X later", call it out as a blocker or force an explicit deferral with a stated reason and documented constraints for whoever picks it up later.
- **Track decisions.** Keep a running list of resolved decisions. Reference them when they constrain later branches.
- **Propose defaults.** When something is ambiguous, stake out a position based on existing code/patterns and let the user correct you. This is faster than open-ended questions.

## Question Hierarchy

Start foundational, work outward:

1. **Data model** — Entities, fields, relationships, nullability, source of truth
2. **Behavior** — Happy path, error cases, edge cases, concurrent access
3. **Integration** — Connection to existing code, upstream/downstream impact
4. **Migration** — Current state to target state without breakage
5. **UX** — What the user sees, when, and what happens mid-flow during deploy

## Done Criteria

You're done when:
- Every branch of the design tree has been explored (or the `quick` scope branches are resolved)
- All inter-decision dependencies are resolved
- Hand-waved items are either resolved or explicitly deferred with rationale
- The user confirms shared understanding is complete
- The numbered decision log is presented as the final artifact
