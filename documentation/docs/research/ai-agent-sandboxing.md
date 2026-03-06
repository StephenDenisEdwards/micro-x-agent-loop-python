# AI Agent Sandboxing: Research Report

**Date:** 2026-03-06
**Status:** Research complete
**Relevance:** Compiled mode execution, agent safety, tool isolation

---

## Executive Summary

This report surveys sandboxing approaches across eight AI agent platforms and synthesises best practices from security researchers (Trail of Bits, NVIDIA AI Red Team, UK AISI). The industry is converging on two dominant patterns: lightweight OS-level sandboxing for local/CLI tools and microVM or gVisor-based isolation for cloud-hosted agents. Pure Docker containers are increasingly seen as insufficient for untrusted AI-generated code.

---

## Platform Analysis

### 1. OpenClaw

**Isolation technology:** Docker containers (opt-in, not enabled by default)

**How it works:** When sandbox mode is enabled (`agents.defaults.sandbox.mode: "docker"` or per-agent), each agent session routes exec commands into a Docker container. The Gateway process stays on the host; only tool execution runs inside the sandbox.

**Filesystem isolation:**
- Bind mounts expose host paths with read-only (`:ro`) or read-write (`:rw`) modes
- Dangerous bind sources blocked by default: `docker.sock`, `/etc`, `/proc`, `/sys`, `/dev`
- Hardened configuration uses `read_only: true` to block all writes outside explicitly mounted volumes
- `cap_drop: ALL` strips every Linux capability from the container

**Network isolation:**
- Default `docker.network` is `"none"` (no egress) — package installs fail unless overridden
- Sandboxed browser containers use a dedicated Docker network (`openclaw-sandbox-browser`)

**Process isolation:**
- `validateSandboxSecurity` runs hard checks against Docker configuration before invocation
- Throws on any violation unless corresponding `dangerously*` flag is set

**Notable concerns:** A critical issue (GitHub #7139) notes that the default configuration provides zero isolation — unrestricted filesystem access and plaintext credentials unless sandbox mode is explicitly opted into.

**Sources:**
- [OpenClaw Sandboxing Docs](https://docs.openclaw.ai/gateway/sandboxing)
- [OpenClaw Sandboxing — DeepWiki](https://deepwiki.com/openclaw/openclaw/7.2-sandboxing)
- [AccuKnox — OpenClaw Security](https://accuknox.com/blog/openclaw-security-ai-agent-sandboxing-aispm)

---

### 2. Claude Code (Anthropic)

**Isolation technology:** OS-level primitives — **bubblewrap (bwrap)** on Linux, **sandbox-exec (Apple Seatbelt)** on macOS. No container or VM required.

**How it works:** The sandboxed bash tool uses OS-level primitives to enforce filesystem and network restrictions. These restrictions apply to direct interactions and all spawned scripts, programs, and subprocesses. Open-sourced as [sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime).

**Filesystem isolation:**
- Read/write access to the current working directory only
- Blocks modification of files outside the working directory
- `enableWeakerNestedSandbox` mode allows operation inside Docker without privileged namespaces

**Network isolation:**
- Processes can only access the internet through a Unix domain socket connected to a proxy server running outside the sandbox
- The proxy enforces restrictions on approved domains
- Handles user confirmation for newly requested domains

**Process isolation:**
- Enforced by OS kernel primitives (bubblewrap namespaces on Linux, Seatbelt policies on macOS)
- All child processes inherit parent sandbox restrictions

**Key metric:** Internal testing found sandboxing reduces permission prompts by 84%.

**Sources:**
- [Anthropic Engineering Blog — Claude Code Sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)
- [Claude Code Sandboxing Docs](https://code.claude.com/docs/en/sandboxing)
- [sandbox-runtime on GitHub](https://github.com/anthropic-experimental/sandbox-runtime)

---

### 3. OpenAI Codex Agent

**Isolation technology:** OS-enforced sandboxing — **Seatbelt/sandbox-exec** on macOS, **Landlock + seccomp** on Linux, **WSL-based Linux sandbox** on Windows.

**How it works:** Two-layer enforcement: (1) a sandbox mode defining technical capability boundaries, and (2) an approval policy gating privilege escalation. Cloud version runs agents in isolated OpenAI-managed containers with a two-phase runtime.

**Filesystem isolation:**
- Default `workspace-write` sandbox confines write access to the active workspace
- `.git` protected as read-only whether it appears as a directory or file
- `.agents` and `.codex` directories receive recursive read-only protection

**Network isolation:**
- Network access defaults to disabled across all platforms
- Configurable: full internet, domain allowlists, or no network
- Web search uses a cache (OpenAI-maintained index) instead of live fetches, reducing prompt injection exposure

**Process isolation:**
- Linux: seccomp restricts allowed system calls, Landlock provides fine-grained filesystem control
- Cloud: two-phase runtime — setup phase (with network for deps) then agent phase (offline by default)

**Novel approach:** The cached web search mechanism returns pre-indexed results instead of live content, eliminating a major prompt injection vector.

**Sources:**
- [OpenAI Codex Security Docs](https://developers.openai.com/codex/security/)
- [GPT-5.2-Codex System Card](https://cdn.openai.com/pdf/ac7c37ae-7f4c-4442-b741-2eabdeaf77e0/oai_5_2_Codex.pdf)

---

### 4. Devin (Cognition)

**Isolation technology:** Cloud-based **virtual machines** (each instance runs in its own isolated VM)

**How it works:** Entirely cloud-based. Each task spawns an isolated VM with a full development environment (shell, code editor, browser). Users never install Devin locally.

**Filesystem isolation:**
- Each VM has its own filesystem, completely separate from other instances
- Works on cloned repositories, not user's local files
- Environment variables scrubbed between sessions

**Network isolation:**
- Controlled internet access for research and dependency installation
- Enterprise: AWS PrivateLink or IPSec for private connectivity
- Production access gated with human approval

**Process isolation:**
- Full VM-level isolation — complete kernel separation between instances
- Multiple parallel instances without interference
- Resource measured in Agent Compute Units (ACUs, ~15 min active work each)

**Novel approach:** Two non-negotiable human checkpoints — Planning Checkpoint (before work begins) and Pull Request Checkpoint (before code merges).

**Sources:**
- [Cognition — Introducing Devin](https://cognition.ai/blog/introducing-devin)
- [Cognition — Devin 2.0](https://cognition.ai/blog/devin-2)

---

### 5. SWE-agent

**Isolation technology:** **Docker containers** (default), with support for **AWS Fargate**, **Modal**, or local execution via the **SWE-ReX** runtime abstraction layer.

**How it works:** SWE-agent 1.0 uses SWE-ReX as its execution runtime. The `SWEEnv` class wraps SWE-ReX. On initialization, the system starts a local Docker container or deploys to a remote system. Custom tools (Agent Command Interface / ACI) are installed and made available.

**Filesystem isolation:**
- Standard container filesystem isolation with Docker
- SWE-MiniSandbox variant uses per-instance **mount namespaces and chroot** for lightweight isolation without containerization

**Network isolation:**
- Default: outbound internet access through host network
- Network policy enforcement through proxy configuration

**Process isolation:**
- Docker: Linux namespaces and cgroups
- SWE-ReX communicates with a server inside the container for command execution

**Novel approach:** SWE-MiniSandbox uses Linux mount namespaces and chroot instead of Docker, suitable for massively parallel RL training — thousands of isolated sessions with much lower overhead.

**Sources:**
- [SWE-agent Architecture](https://swe-agent.com/latest/background/architecture/)
- [SWE-ReX on GitHub](https://github.com/SWE-agent/SWE-ReX)
- [SWE-MiniSandbox Paper](https://arxiv.org/html/2602.11210v1)

---

### 6. E2B (e2b.dev)

**Isolation technology:** **Firecracker microVMs** running on KVM (Kernel-based Virtual Machine)

**How it works:** Open-source sandboxing-as-a-service. Each sandbox is a Firecracker microVM with its own kernel, providing hardware-level isolation. SDKs available in JavaScript and Python.

**Filesystem isolation:**
- Each microVM has a completely isolated filesystem
- Secure mode: signature-based file access control — uploads/downloads require cryptographic signatures
- Sandboxes can run for up to 24 hours

**Network isolation:**
- Each microVM has isolated networking via its own kernel
- No shared kernel eliminates network namespace escape vectors

**Process isolation:**
- Hardware-level isolation via KVM hypervisor
- Each microVM runs its own Linux kernel
- Firecracker's minimal codebase (~50K lines of Rust) reduces attack surface vs QEMU

**Performance:**
- Boot time: ~125ms
- Memory overhead: <5 MiB per microVM
- Creation rate: up to 150 microVMs/second per host
- Limitation: no GPU/PCIe support

**Notable:** Used by Manus (the viral AI agent) as its compute backend.

**Sources:**
- [E2B Homepage](https://e2b.dev/)
- [E2B — Firecracker vs QEMU](https://e2b.dev/blog/firecracker-vs-qemu)
- [How Manus Uses E2B](https://e2b.dev/blog/how-manus-uses-e2b-to-provide-agents-with-virtual-computers)

---

### 7. Modal

**Isolation technology:** **gVisor** (user-space kernel / application kernel)

**How it works:** Workloads run inside gVisor, which intercepts system calls in user-space before they reach the host kernel. The Sentry component acts as an application kernel. A separate Gofer process handles filesystem operations via 9P protocol.

**Filesystem isolation:**
- Gofer process acts as a trusted filesystem proxy
- Per-job PID + mount + IPC namespaces for per-execution isolation
- Ephemeral tmpfs for writable paths, cleaned up via single `umount2` syscall
- Memory and filesystem snapshots for quick agent resume

**Network isolation:**
- Secure-by-default: no incoming connections, no Modal resource access
- Outbound restricted via `cidr_allowlist` parameter
- Options: no networking, domain-level allowlist proxy, or explicit capability grants
- DNS blocked inside sandbox, forced through proxy

**Process isolation:**
- gVisor intercepts all syscalls via Sentry — host kernel never sees raw application syscalls
- Only minimal, vetted subset of host syscalls allowed
- Scales to 50,000+ simultaneous sandboxes
- SOC2 and HIPAA compliant

**Performance:** 10-30% overhead on I/O-heavy workloads, minimal on compute-heavy tasks.

**Sources:**
- [Modal — Secure Execution for Coding Agents](https://modal.com/solutions/coding-agents)
- [Modal — Sandbox Networking Docs](https://modal.com/docs/guide/sandbox-networking)
- [gVisor Architecture Guide](https://gvisor.dev/docs/architecture_guide/intro/)

---

### 8. Daytona

**Isolation technology:** **OCI/Docker containers** with optimised orchestration

**How it works:** Pivoted in February 2025 from developer environments to infrastructure for running AI-generated code. Uses container-based isolation with OCI/Docker compatibility and sub-90ms startup via warm sandbox pools.

**Filesystem isolation:**
- Each sandbox runs in an isolated container
- Default resources: 1 vCPU, 1GB RAM, 3GiB disk
- Stopped sandboxes maintain filesystem persistence (memory state cleared)
- Archived sandboxes: filesystem state moved to object storage for long-term retention

**Network isolation:**
- Configurable firewall controls
- Restricted network access by default

**Process isolation:**
- Container-level via Linux namespaces and cgroups
- Sandboxes run on customer-managed compute; Daytona provides the control plane
- Comprehensive API for process execution, file operations, Git integration

**Novel approach:** Warm sandbox pool for <90ms startup. Object storage archival for long-running workflows. Agent-agnostic middleware (works with OpenHands, Claude Code, etc.).

**Sources:**
- [Daytona Homepage](https://www.daytona.io/)
- [Daytona on GitHub](https://github.com/daytonaio/daytona)
- [Daytona Sandboxes Docs](https://www.daytona.io/docs/en/sandboxes/)

---

## Comparison Matrix

| Platform | Isolation Tech | Filesystem | Network | Boot Time | Novel Feature |
|---|---|---|---|---|---|
| **OpenClaw** | Docker (opt-in) | Bind mounts + blocklist | Default none | Standard Docker | Security validation checks |
| **Claude Code** | bubblewrap / Seatbelt | CWD-only writes | Unix socket proxy | Instant | OS-level, zero container overhead |
| **OpenAI Codex** | Landlock+seccomp / Seatbelt | Workspace-only writes | Default disabled | Instant | Cached web search anti-injection |
| **Devin** | Cloud VMs | Full VM isolation | Controlled, gated | VM boot | Human checkpoint gates |
| **SWE-agent** | Docker / Modal / AWS | Container or chroot | Via host network | Standard Docker | mount namespace + chroot variant |
| **E2B** | Firecracker microVMs | Hardware-isolated | Hardware-isolated | ~125ms | Disposable VMs, crypto file access |
| **Modal** | gVisor | Gofer proxy + tmpfs | CIDR allowlist proxy | <1 second | Syscall interception layer |
| **Daytona** | OCI containers | Container-isolated | Firewall controls | <90ms | Warm pool + object storage archive |

---

## Best Practices (2025–2026)

Based on research from NVIDIA AI Red Team, Trail of Bits, Northflank, and the UK AISI.

### Mandatory Controls

1. **Network egress controls** — Block network access to arbitrary sites. Prevents data exfiltration and remote shells. Default-deny with tightly scoped allowlists.

2. **Filesystem write restrictions** — Block writes outside the workspace. Prevents persistence mechanisms, sandbox escapes, and RCE. Critical targets to protect: shell init files (`.zshrc`, `.bashrc`), binary directories (`~/.local/bin`), SSH keys.

3. **Configuration file protection** — Block writes to agent config files (`.cursorrules`, `CLAUDE.md`, MCP configurations, git hooks) that often execute outside sandbox context. Prime targets for prompt injection persistence.

### Defence-in-Depth Layers

```
Layer 1: OS-level sandboxing (mandatory foundation)
Layer 2: Network egress controls (default-deny + allowlist)
Layer 3: Filesystem write restrictions (workspace-only)
Layer 4: Config file protection (block agent config writes)
Layer 5: Human approval gates (enforced at OS level, not app level)
Layer 6: Short-lived credentials per task
Layer 7: Periodic sandbox destruction + immutable audit logs
```

### Technology Selection Guide

| Use Case | Recommended Isolation |
|---|---|
| Trusted/reviewed code only | Docker containers |
| Multi-tenant SaaS, CI/CD | gVisor |
| Untrusted AI-generated code | Firecracker microVMs or Kata Containers |
| Regulated industries on Kubernetes | Kata Containers |
| Local CLI tools | bubblewrap (Linux) / Seatbelt (macOS) |

---

## Security Considerations: Prompt Injection to Sandbox Escape

### Documented Attack Vectors

1. **Argument injection** (Trail of Bits, 2025) — Attackers bypass human-approved commands by injecting flags. Examples:
   - `go test -exec` allows arbitrary program execution within an "approved" test command
   - `git show --format --output` can create files
   - `ripgrep --pre bash` can execute arbitrary scripts

2. **Living off the land** — Using legitimate system utilities (GTFOBINS/LOLBINS) to achieve malicious goals without introducing new binaries. Command allowlists without sandboxing are "fundamentally flawed" due to the astronomical number of parameter combinations.

3. **Configuration poisoning** — Embedding malicious instructions in repository files (`.cursorrules`, `CLAUDE.md`, git hooks) that agents read and execute. These persist across sessions.

4. **Cascading prompt injection** — Malicious prompts embedded in code comments, GitHub issues, or logging output trick agents into generating exploit code.

5. **Real-world sandbox escape (CVE-2026-27952)** — A Python sandbox escape in Agenta-API where `numpy` was allowlisted as "safe" but `numpy.ma.core.inspect` exposed Python introspection utilities (`sys.modules`), enabling access to `os.system`. CVSS 8.8.

### Key Insight

> "Maintaining allowlists without sandboxing is fundamentally flawed."
> — Trail of Bits, 2025

OS-level sandboxing is the essential foundation; allowlists and approval gates are secondary layers.

---

## Relevant Academic & Industry Papers

1. **"Systems Security Foundations for Agentic Computing"** (Christodorescu et al., December 2025, IEEE SAGAI) — 11 case studies of real attacks on agentic systems. [arXiv:2512.01295](https://arxiv.org/abs/2512.01295)

2. **"SWE-MiniSandbox: Container-Free RL for Building SWE Agents"** (2026) — Linux mount namespaces + chroot for lightweight parallel isolation. [arXiv:2602.11210](https://arxiv.org/html/2602.11210v1)

3. **"The 2025 AI Agent Index"** — Technical and safety features of deployed agentic systems. [arXiv:2602.17753](https://arxiv.org/html/2602.17753)

4. **AISI Inspect Sandboxing Toolkit** — UK AI Security Institute's open-source framework. Classifies isolation along three axes: tooling, host, network. [AISI Blog](https://www.aisi.gov.uk/blog/the-inspect-sandboxing-toolkit-scalable-and-secure-ai-agent-evaluations)

5. **NVIDIA AI Red Team — Sandboxing Agentic Workflows** — Practical attack experience. [NVIDIA Blog](https://developer.nvidia.com/blog/practical-security-guidance-for-sandboxing-agentic-workflows-and-managing-execution-risk/)

6. **Trail of Bits — "Prompt Injection to RCE in AI Agents"** (October 2025) — Three classes of argument injection attacks. [Trail of Bits Blog](https://blog.trailofbits.com/2025/10/22/prompt-injection-to-rce-in-ai-agents/)

---

## Applicability to micro-x-agent-loop

For compiled mode execution (when implemented), the most applicable approaches are:

- **E2B or Modal** as a hosted sandbox backend for batch task execution
- **bubblewrap** for local CLI sandboxing (the Claude Code approach)
- **Proxy-based network control** to restrict tool access to approved domains
- **Human approval gates** at the OS level, not just the application level — aligns with the existing interactive mode prompt
