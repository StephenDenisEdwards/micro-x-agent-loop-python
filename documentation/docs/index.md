# micro-x-agent-loop-python Documentation

Central navigation hub for all project documentation.

## Quick Start

- [Getting Started](operations/getting-started.md) - Setup, prerequisites, first run

## Architecture

- [Software Architecture Document](architecture/SAD.md) - System overview, components, data flow
- [Architecture Decision Records](architecture/decisions/README.md) - Index of all ADRs

## Design

- [Agent Loop Design](design/DESIGN-agent-loop.md) - Core agent loop, tool dispatch, streaming
- [Tool System Design](design/DESIGN-tool-system.md) - Tool interface, registry, built-in tools

## Operations

- [Getting Started](operations/getting-started.md) - Prerequisites, setup, running
- [Configuration Reference](operations/config.md) - All settings with types and defaults
- [Troubleshooting](operations/troubleshooting.md) - Common issues and solutions

## Document Map

```mermaid
graph TD
    INDEX[index.md] --> SAD[SAD.md]
    INDEX --> ADR[ADR Index]
    INDEX --> DESIGN1[Agent Loop Design]
    INDEX --> DESIGN2[Tool System Design]
    INDEX --> OPS1[Getting Started]
    INDEX --> OPS2[Configuration]
    INDEX --> OPS3[Troubleshooting]

    ADR --> ADR001[ADR-001: python-dotenv for Secrets]
    ADR --> ADR002[ADR-002: tenacity for Retry]
    ADR --> ADR003[ADR-003: Streaming Responses]

    SAD --> DESIGN1
    SAD --> DESIGN2
    OPS2 --> OPS3
```
