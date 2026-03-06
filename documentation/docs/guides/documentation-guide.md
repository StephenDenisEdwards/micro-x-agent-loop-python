# Guide: Documentation

Where each type of document goes, naming conventions, templates, and how to keep the docs consistent.

## Directory Structure

```
/
├── CLAUDE.md                    AI assistant context (update when adding key files/conventions)
├── CONTRIBUTING.md              Contributor guide
├── CHANGELOG.md                 Curated feature history
├── README.md                    Project overview (promotional)
├── QUICKSTART.md                Getting started guide (practical)
│
├── documentation/docs/
│   ├── index.md                 Central navigation hub — UPDATE when adding new docs
│   │
│   ├── architecture/
│   │   ├── SAD.md               Software Architecture Document (single file, versioned)
│   │   └── decisions/
│   │       ├── README.md        ADR index table — UPDATE when adding new ADRs
│   │       └── ADR-NNN-*.md     Architecture Decision Records
│   │
│   ├── design/
│   │   ├── DESIGN-*.md          Core system design documents
│   │   └── tools/
│   │       └── <tool>/README.md Per-tool documentation
│   │
│   ├── operations/              User-facing: how to run, configure, troubleshoot
│   ├── guides/                  Developer-facing: how to extend, debug, contribute
│   ├── planning/
│   │   ├── INDEX.md             Priority queue and status — UPDATE when plans change
│   │   └── PLAN-*.md            Feature plans
│   │
│   ├── research/
│   │   ├── README.md            Research index with themes
│   │   └── *.md                 Framework studies, surveys, analysis
│   │
│   ├── research-papers/         Formal papers and white papers
│   ├── examples/                Prompt packs and workflow examples
│   ├── openclaw-research/       OpenClaw-specific deep dives
│   ├── best-practice/           Conventions and best practices
│   └── issues/                  Issue resolution records
```

## Document Types and Templates

### Architecture Decision Records (ADRs)

**Location:** `architecture/decisions/ADR-NNN-<slug>.md`
**Naming:** Sequential number, kebab-case slug: `ADR-018-my-decision.md`
**When:** Any significant architectural choice — technology selection, pattern adoption, structural change.

```markdown
# ADR-NNN: Title

## Status
Proposed | Accepted | Deprecated | Superseded by ADR-YYY

## Context
What is the issue that we're seeing that is motivating this decision or change?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?
```

**After creating:** Add a row to the index table in `architecture/decisions/README.md`.

### Design Documents

**Location:** `design/DESIGN-<name>.md`
**Naming:** `DESIGN-` prefix, kebab-case: `DESIGN-my-feature.md`
**When:** Documenting how a major system component works — its structure, data model, component interactions, and design rationale.

Typical sections:
- Overview
- Package/module structure
- Data model (if applicable)
- Component interactions
- Related documentation (links to ADRs, plans, operations docs)

### Per-Tool Documentation

**Location:** `design/tools/<tool-name>/README.md`
**When:** Each MCP tool or tool group gets its own README.

Include:
- Tool name and description
- Parameters with types
- Example input/output
- Related ADRs

### Planning Documents

**Location:** `planning/PLAN-<name>.md`
**Naming:** `PLAN-` prefix, kebab-case: `PLAN-my-feature.md`
**When:** Before starting non-trivial feature work.

Typical sections:
- Goal / motivation
- Phases with scope and deliverables
- Status tracking per phase
- Related ADRs and design docs

**After creating:** Add a row to `planning/INDEX.md` in both the priority queue and the "All Plans" table.

**After completing:** Update the status in `INDEX.md` and note the completion date.

### Operations Documents

**Location:** `operations/<name>.md`
**When:** User-facing how-to content — setup, configuration, troubleshooting, feature guides.

Keep these practical: steps, tables, examples. Minimal theory.

### Developer Guides

**Location:** `guides/<name>.md`
**When:** Developer-facing how-to content — extending the system, debugging, contributing.

These explain internal architecture patterns and provide step-by-step instructions for common development tasks.

### Research Documents

**Location:** `research/<name>.md`
**When:** Studying external frameworks, technologies, or approaches to inform project decisions.

Include sources and links. Relate findings back to the project where relevant.

### Issue Resolution Records

**Location:** `issues/ISSUE-NNN-<slug>.md`
**When:** A significant issue is discovered and resolved, especially if it corrects an ADR or design assumption.

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| ADR | `ADR-NNN-kebab-slug.md` | `ADR-018-sandbox-execution.md` |
| Design | `DESIGN-kebab-name.md` | `DESIGN-sandbox-runtime.md` |
| Plan | `PLAN-kebab-name.md` | `PLAN-sandbox-integration.md` |
| Issue | `ISSUE-NNN-kebab-slug.md` | `ISSUE-002-config-race-condition.md` |
| Operations | `kebab-name.md` | `voice-mode.md` |
| Guides | `kebab-name.md` | `adding-an-mcp-server.md` |
| Research | `kebab-name.md` | `ai-agent-sandboxing.md` |

## Cross-Referencing

Use relative markdown links between documents:

```markdown
- From design to ADR: [ADR-009](../architecture/decisions/ADR-009-sqlite-memory-sessions-and-file-checkpoints.md)
- From guide to design: [Memory System Design](../design/DESIGN-memory-system.md)
- From operations to guide: [Adding an MCP Server](../guides/adding-an-mcp-server.md)
```

Include a "Related" section at the bottom of every document linking to relevant ADRs, design docs, and plans.

## Updating Indexes

When you add a new document, update these files:

| New Doc Type | Update These |
|-------------|-------------|
| ADR | `architecture/decisions/README.md` (index table) |
| Plan | `planning/INDEX.md` (priority queue + all plans table) |
| Any | `index.md` (if it belongs in the navigation hub) |
| Key file/convention | `CLAUDE.md` (if it changes how AI assistants should work with the project) |

## Formatting Standards

- **Headings:** Use `##` for main sections, `###` for subsections. Only one `#` per file (the title).
- **Tables:** Use for structured data (parameters, comparisons, indexes).
- **Code blocks:** Use fenced blocks with language tags (```python, ```json, ```bash).
- **Links:** Relative paths to other docs. Full URLs for external references.
- **Line length:** No hard wrap — let the renderer handle it.
- **Mermaid diagrams:** Use where they add clarity (architecture, flows, relationships). Not every doc needs one.

## Checklist for New Documents

- [ ] File is in the correct directory
- [ ] Filename follows the naming convention
- [ ] Title matches the filename intent
- [ ] "Related" section links to relevant ADRs, design docs, plans
- [ ] Relevant indexes are updated (ADR README, planning INDEX, index.md)
- [ ] CLAUDE.md updated if the doc introduces new key files or conventions
