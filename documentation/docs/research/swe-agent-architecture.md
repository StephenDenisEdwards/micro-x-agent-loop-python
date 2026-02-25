# SWE-agent Architecture Research

> **Date**: 2026-02-25
> **Subject**: Princeton SWE-agent — Agent-Computer Interface for Automated Software Engineering
> **Repository**: <https://github.com/SWE-agent/SWE-agent> (formerly `princeton-nlp/SWE-agent`)
> **Documentation**: <https://swe-agent.com>
> **Paper**: Yang et al., "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering" (NeurIPS 2024) — [arXiv:2405.15793](https://arxiv.org/abs/2405.15793)
> **License**: MIT
> **Language**: Python 3.11+

---

## 1. Overview

SWE-agent is a research-grade autonomous software engineering system developed by
researchers at Princeton University and Stanford University. Given a GitHub issue or
problem statement, SWE-agent uses a language model to autonomously navigate a
repository, locate relevant code, create/edit files, run tests, and produce a patch
that resolves the issue.

### Core philosophy

SWE-agent is built on a single powerful insight: **LM agents are a new category of
end users with their own needs and abilities**, and the interface between the agent
and the computer matters enormously. Rather than giving a model raw shell access and
hoping for the best, SWE-agent designs a purpose-built *Agent-Computer Interface*
(ACI) — a constrained set of tools, feedback formats, and guardrails — that makes it
dramatically easier for the LM to perform software engineering tasks.

### Key results (original paper)

| Benchmark      | Pass@1 Rate | Notes                                    |
|----------------|-------------|------------------------------------------|
| SWE-bench      | 12.5%       | SOTA among open-source at time of paper  |
| HumanEvalFix   | 87.7%       | Far exceeding prior non-interactive LMs  |

The paper's ablation studies showed that the custom ACI solved **10.7 percentage
points more** SWE-bench Lite instances than an agent with only a default Linux shell
— demonstrating that interface design is a first-class concern for agent performance.

### Tech stack and dependencies

- **Language**: Python 3.11+
- **Build system**: setuptools via `pyproject.toml`
- **LLM integration**: [LiteLLM](https://github.com/BerriAI/litellm) (unified multi-provider API)
- **Execution runtime**: [SWE-ReX](https://github.com/SWE-agent/SWE-ReX) (sandboxed shell execution)
- **Retry logic**: [tenacity](https://pypi.org/project/tenacity/)
- **Config/YAML**: ruamel.yaml
- **Prompt templates**: Jinja2-style variable substitution
- **Other deps**: datasets, numpy, pandas, rich, unidiff
- **Container backend**: Docker (default), Podman, Modal, AWS Fargate, Daytona

### Repository structure (top-level)

```
SWE-agent/
├── sweagent/           # Core Python package
│   ├── agent/          # Agent classes, models, history processors, parsers
│   │   ├── agents.py   # AbstractAgent, DefaultAgent, RetryAgent
│   │   ├── models.py   # LiteLLMModel, HumanModel, ReplayModel
│   │   └── ...
│   ├── environment/    # SWEEnv wrapper around SWE-ReX
│   │   └── swe_env.py
│   └── ...
├── config/             # YAML configuration files
│   └── default.yaml    # Default agent config
├── tools/              # Tool bundles (ACI command implementations)
│   ├── registry/       # Core tool registry
│   ├── edit_anthropic/ # str_replace_editor tool bundle
│   └── review_on_submit_m/
├── trajectories/       # Demonstration trajectories
├── tests/
├── docs/
└── pyproject.toml
```

---

## 2. Agent-Computer Interface (ACI) — The Core Innovation

The ACI is the defining contribution of SWE-agent. It is the set of **custom
commands, feedback formats, and guardrails** that mediate every interaction between
the LM and the computer.

### Design principles

1. **Constrain the action space**: Rather than exposing the full Linux shell (which
   has an enormous, ambiguous action space), provide a small set of well-documented
   commands with clear semantics.

2. **Optimize feedback for LM consumption**: Raw shell output is often verbose,
   poorly formatted, or ambiguous. The ACI formats every observation to be concise
   and unambiguous for the model.

3. **Prevent common failure modes**: A built-in linter rejects syntactically invalid
   edits before they are applied. An explicit "no output" message prevents confusion
   when commands succeed silently.

4. **Minimize cognitive load**: The file viewer shows exactly 100 lines per turn
   (not the entire file), forcing the agent into a manageable "zoom-in" workflow.

### ACI components

| Component              | Purpose                                                |
|------------------------|--------------------------------------------------------|
| **File viewer**        | Custom viewer displaying ~100 lines with line numbers  |
| **File editor**        | `str_replace` / `insert` / `create` / `undo_edit`     |
| **Search/navigation**  | `find_file`, `search_file`, `search_dir`               |
| **Linter**             | Validates syntax on every edit; rejects bad edits      |
| **Scroll commands**    | `scroll_up`, `scroll_down`, `goto` for navigation      |
| **Bash access**        | Full bash still available for running tests, etc.      |
| **State command**      | Runs after every action; returns JSON context (open_file, working_dir) |
| **Feedback templates** | Explicit formatting for output, no-output, and errors  |

### Ablation results (from the paper, on SWE-bench Lite subset of 300 instances)

| Variant                    | Relative Impact                       |
|----------------------------|---------------------------------------|
| Full SWE-agent ACI         | Baseline (best performance)           |
| Shell-only (no ACI)        | -10.7 percentage points               |
| No edit command             | -7.7 percentage points                |
| No linter/guardrails       | -3.0 percentage points                |

The results definitively show that each ACI component contributes meaningfully to
performance. The edit command is the single most impactful component, and the linter
provides a substantial additional boost.

### Why this matters vs. raw shell access

A raw-shell agent must:
- Figure out how to use `cat`, `sed`, `grep`, `find` correctly every time
- Parse verbose, inconsistent terminal output
- Manage its own file editing (often producing syntax errors)
- Deal with silent command success vs. failure ambiguity

The ACI eliminates these problems by providing a small, well-documented set of
commands with predictable output formats. This is analogous to how GUIs constrain
human-computer interaction to make it more reliable — except the ACI is designed for
LM "cognition" rather than human cognition.

---

## 3. Agent Loop Lifecycle

The main agent loop follows a clear sequential pattern orchestrated by the
`RunOrchestrator`, `Agent`, and `SWEEnv` classes.

### High-level flow

```
CLI (sweagent run)
  └→ RunOrchestrator
       ├→ Initialize Agent (DefaultAgent or RetryAgent)
       ├→ Initialize SWEEnv (Docker container via SWE-ReX)
       └→ Agent.run(env, problem_statement, output_dir)
            ├→ Agent.setup()
            │    ├→ Format system_template with {command_docs}, env vars
            │    ├→ Add system message to history
            │    ├→ Add demonstrations to history (optional)
            │    └→ Format instance_template with {problem_statement}, {working_dir}
            ├→ Main loop: while not done
            │    └→ Agent.step()
            │         ├→ forward_with_handling(self.messages)
            │         │    ├→ Apply HistoryProcessors (compress history)
            │         │    ├→ Query model (LiteLLMModel)
            │         │    ├→ Parse response → (thought, action) via ToolHandler
            │         │    ├→ handle_action(step) → execute in SWEEnv
            │         │    │    ├→ Check blocklist
            │         │    │    ├→ env.communicate(action, timeout)
            │         │    │    └→ Return observation
            │         │    └→ Handle errors (requery up to max_requeries)
            │         ├→ Format observation via next_step_template
            │         ├→ add_step_to_history(step)
            │         ├→ add_step_to_trajectory(step)
            │         └→ Check exit conditions
            └→ save_trajectory() → .traj JSON file
```

### Step-by-step detail

1. **History compression**: Before each model call, `HistoryProcessor` instances
   compress the message history to fit within the context window. The default
   processor keeps recent interactions (typically the last ~5 steps) in full detail
   while condensing older messages.

2. **Model query**: The `LiteLLMModel.query()` method sends the compressed history
   to the configured LLM provider. It includes pre-flight token counting to validate
   against context window limits, cost tracking, and retry logic via tenacity with
   exponential backoff.

3. **Action parsing**: The `ToolHandler.parse_actions()` method extracts a
   `(thought, action)` pair from the model response using the configured parser (see
   Section 5 below for parser types).

4. **Action execution**: `handle_action()` runs the parsed command in the sandboxed
   environment via `SWEEnv.communicate()`. The environment returns stdout/stderr as
   the observation.

5. **Observation formatting**: The observation is formatted using Jinja2-style
   templates:
   - `next_step_template`: Normal output — `"OBSERVATION:\n{{observation}}"`
   - `next_step_no_output_template`: Silent success — `"Your command ran
     successfully and did not produce any output."`
   - Truncated template: When output exceeds `max_observation_length`, the middle
     is elided with a character count.

6. **State extraction**: After every action, the `state_command` (e.g., `_state` or
   `_state_anthropic`) runs and returns a JSON dict with context like `open_file`
   and `working_dir`. These variables are available in templates.

7. **Trajectory recording**: Each step is recorded as a `TrajectoryStep` containing
   action, observation, thought, execution time, environment state, and model
   response metadata. The full trajectory is saved to a `.traj` JSON file.

8. **Exit conditions**: The loop terminates when:
   - The agent issues a `submit` command
   - Cost limits are exceeded (`InstanceCostLimitExceededError`,
     `TotalCostLimitExceededError`)
   - Step limits are reached
   - 5 consecutive command timeouts occur (triggers auto-submission)

### Error recovery

`forward_with_handling()` implements robust error recovery with requerying:

| Error Type                | Handling                                           |
|---------------------------|----------------------------------------------------|
| `FormatError`             | Requery with `format_error_template`               |
| `_BlockedActionError`     | Requery with blocklist violation message            |
| `BashIncorrectSyntaxError`| Requery with syntax error details                  |
| `ContextWindowExceeded`   | Attempt auto-submission with current patch          |
| `CostLimitExceeded`       | Attempt auto-submission with current patch          |
| `CommandTimeoutError`     | Retry with interrupt; auto-submit after 5 timeouts |

The `max_requeries` parameter (default: 3) controls how many times the model is
re-prompted after a recoverable error before giving up on that step.

---

## 4. Command System

SWE-agent replaces raw shell interaction with a curated set of custom commands
organized into **tool bundles**.

### Tool bundle structure

Each bundle is a directory with:

```
tools/<bundle_name>/
├── bin/              # Executable scripts (bash or Python)
│   ├── <command>     # Tool implementation
│   └── _state        # State extraction command (optional)
├── config.yaml       # Tool definitions (signatures, docstrings, arguments)
├── install.sh        # Dependency installation (optional)
├── lib/              # Shared libraries (optional)
├── README.md
└── pyproject.toml
```

### Default tool bundles

The default configuration (`config/default.yaml`) loads three bundles:

```yaml
bundles:
  - path: tools/registry        # Core search/navigation tools
  - path: tools/edit_anthropic  # str_replace_editor (file editing)
  - path: tools/review_on_submit_m  # Submission review workflow
```

### Tool config format (`config.yaml`)

```yaml
tools:
  tool_name:
    signature: "tool_name <arg1> [<arg2>]"
    docstring: "Description helping the LM understand when/how to use this tool"
    arguments:
      - name: arg1
        type: string
        description: "What this argument does"
        required: true
      - name: arg2
        type: integer
        description: "Optional argument"
        required: false

state_command: "_state"  # Runs after every action, returns JSON
```

### The `str_replace_editor` tool (from `edit_anthropic` bundle)

This is the primary file editing tool, supporting five operations:

**Signature:**
```
str_replace_editor <command> <path> [<file_text>] [<view_range>] [<old_str>] [<new_str>] [<insert_line>]
```

| Command       | Description                                            |
|---------------|--------------------------------------------------------|
| `view`        | Display file contents or directory listing             |
| `create`      | Create a new file with specified content               |
| `str_replace` | Replace `old_str` with `new_str` in the file           |
| `insert`      | Insert content after a specified line number           |
| `undo_edit`   | Revert the most recent edit                            |

**Arguments:**
- `command` (string, required) — the operation to perform
- `path` (string, required) — absolute path to the file
- `file_text` (string, optional) — content for `create`
- `old_str` (string, optional) — text to find for `str_replace`
- `new_str` (string, optional) — replacement text
- `insert_line` (integer, optional) — line number for `insert`
- `view_range` (array, optional) — `[start, end]` line numbers for `view`

The editor includes a **built-in linter** that validates syntax after every edit. If
the edit introduces a syntax error, it is rejected and the agent is notified — the
file is not modified. This prevents the common failure mode of agents introducing
broken code.

### Search and navigation commands (from `registry` bundle)

| Command        | Description                                                 |
|----------------|-------------------------------------------------------------|
| `find_file`    | Search for filenames matching a pattern in the repository   |
| `search_file`  | Search for a string within a single file                    |
| `search_dir`   | Search for a string across files in a directory             |
| `open`         | Open a file in the viewer (displays ~100 lines)             |
| `goto`         | Jump to a specific line number in the open file             |
| `scroll_up`    | Scroll the file viewer up                                   |
| `scroll_down`  | Scroll the file viewer down                                 |

**Design decision — succinct search results**: The `search_dir` command lists only
the files containing matches, not extensive context around each match. The designers
found that showing too much context confused the model's reasoning. This forces a
deliberate "search → open → read" workflow.

### Bash access

In addition to the custom commands, the agent retains full bash access for running
tests, installing dependencies, and executing arbitrary commands:

```yaml
enable_bash_tool: true
```

This is critical because the agent needs to run test suites (`pytest`, etc.) and
perform operations not covered by the custom tool set.

### Environment variables set for the shell

```yaml
env_variables:
  PAGER: cat
  MANPAGER: cat
  LESS: -R
  PIP_PROGRESS_BAR: 'off'
  TQDM_DISABLE: '1'
  GIT_PAGER: cat
```

These variables prevent interactive pagers and progress bars that would confuse the
agent with unexpected output formats.

---

## 5. Configuration and Templates

SWE-agent is governed by a single YAML configuration file that controls every aspect
of agent behavior.

### Configuration hierarchy

Configuration is assembled from three sources (in order of precedence):
1. CLI arguments (highest)
2. Environment variables
3. YAML config files (lowest)

### Agent config types

SWE-agent supports three agent configuration classes:

#### `DefaultAgentConfig` (primary)

```python
class DefaultAgentConfig:
    name: str = 'main'
    templates: TemplateConfig       # Prompt templates
    tools: ToolConfig               # Tool bundles and settings
    history_processors: list[HistoryProcessor]  # Context compression
    model: ModelConfig              # LLM provider settings
    max_requeries: int = 3          # Error retry limit
    action_sampler: ActionSamplerConfig | None = None
    type: Literal['default'] = 'default'
```

#### `RetryAgentConfig` (meta-agent)

Runs multiple `DefaultAgent` attempts and selects the best solution:

```python
class RetryAgentConfig:
    name: str = 'retry_main'
    agent_configs: list[DefaultAgentConfig]  # Per-attempt configs
    retry_loop: RetryLoopConfig              # Retry strategy
    type: Literal['retry'] = 'retry'
```

#### `ShellAgentConfig` (interactive/experimental)

For human-in-the-loop mode via `sweagent sh`:

```python
class ShellAgentConfig:
    name: str = 'main'
    templates: TemplateConfig
    tools: ToolConfig
    history_processors: list[HistoryProcessor]
    model: ModelConfig
    max_requeries: int = 3
    type: Literal['shell'] = 'shell'
```

### Prompt templates

Templates use Jinja2-style `{{variable}}` substitution. Available variables include:

| Variable              | Source                                          |
|-----------------------|-------------------------------------------------|
| `{{command_docs}}`    | Auto-generated from tool bundle `config.yaml`   |
| `{{observation}}`     | Last command output                              |
| `{{problem_statement}}`| From the task/issue                             |
| `{{working_dir}}`     | From state command JSON                         |
| `{{open_file}}`       | From state command JSON                         |
| `{{diff}}`            | Current git diff (used in review templates)     |

#### `system_template` — First system message

```yaml
system_template: |-
  You are a helpful assistant that can interact with a computer to solve tasks.
```

In practice, this is extended to describe the available commands (via
`{{command_docs}}`), the file editor interface, and expected behavior patterns.

#### `instance_template` — Task prompt

```yaml
instance_template: |-
  <uploaded_files>
  {{working_dir}}
  </uploaded_files>
  I've uploaded a python code repository in the directory {{working_dir}}.
  Consider the following PR description:

  <pr_description>
  {{problem_statement}}
  </pr_description>

  Can you help me implement the necessary changes to the repository so that
  the requirements specified in the <pr_description> are met?
  ...
  Follow these steps to resolve the issue:
  1. As a first step, find and read code relevant to the <pr_description>
  2. Create a script to reproduce the error and execute it
  3. Edit the sourcecode of the repo to resolve the issue
  4. Rerun your reproduce script and confirm that the error is fixed!
  5. Think about edgecases and make sure your fix handles them as well
```

#### `next_step_template` — Per-turn observation

```yaml
next_step_template: |-
  OBSERVATION:
  {{observation}}
```

#### `next_step_no_output_template` — Silent success

```yaml
next_step_no_output_template: |-
  Your command ran successfully and did not produce any output.
```

#### `format_error_template` — Malformed response

Shown when the model's output cannot be parsed by the configured action parser. The
agent is re-queried with this error message up to `max_requeries` times.

### Default config example (`config/default.yaml`)

```yaml
agent:
  templates:
    system_template: |-
      You are a helpful assistant that can interact with a computer to solve tasks.
    instance_template: |-
      <uploaded_files>
      {{working_dir}}
      </uploaded_files>
      I've uploaded a python code repository in the directory {{working_dir}}.
      Consider the following PR description:

      <pr_description>
      {{problem_statement}}
      </pr_description>

      Can you help me implement the necessary changes...
      ...
    next_step_template: |-
      OBSERVATION:
      {{observation}}
    next_step_no_output_template: |-
      Your command ran successfully and did not produce any output.

  tools:
    env_variables:
      PAGER: cat
      MANPAGER: cat
      LESS: -R
      PIP_PROGRESS_BAR: 'off'
      TQDM_DISABLE: '1'
      GIT_PAGER: cat
    bundles:
      - path: tools/registry
      - path: tools/edit_anthropic
      - path: tools/review_on_submit_m
    registry_variables:
      USE_FILEMAP: 'true'
      SUBMIT_REVIEW_MESSAGES:
        - |
          Thank you for your work on this issue. Please carefully follow the
          steps below to help review your changes.
          1. If you made any changes after running the reproduction script,
             please run it again...
          2. Remove your reproduction script...
          3. If you modified TEST files, revert them...
          4. Run the submit command again to confirm.

          <diff>
          {{diff}}
          </diff>
    enable_bash_tool: true
    parse_function:
      type: function_calling

  history_processors:
    - type: cache_control
      last_n_messages: 2
```

---

## 6. Environment and Sandboxing

SWE-agent executes all agent commands in a sandboxed environment managed by
**SWE-ReX** (SWE Runtime for Execution).

### SWE-ReX architecture

SWE-ReX is a standalone package that provides a runtime interface for interacting
with sandboxed shell environments. It was factored out of SWE-agent to be reusable
by other agent frameworks.

Key capabilities:
- **Shell session management**: Recognizes command completion, extracts output and
  exit codes
- **Interactive tool support**: Handles `ipython`, `gdb`, and similar CLIs
- **Parallel execution**: Manages multiple concurrent sessions
- **Multi-backend**: Abstracts execution across Docker, Modal, AWS Fargate, etc.

### How it works

```
SWE-agent (Agent class)
  └→ SWEEnv (environment wrapper)
       └→ SWE-ReX Deployment
            └→ RemoteRuntime
                 └→ swerex-remote (server inside container)
                      └→ Shell session (bash)
```

1. `SWEEnv` initializes a SWE-ReX deployment (e.g., `DockerDeployment`).
2. The deployment starts a container from a specified image (default:
   `python:3.11`).
3. Inside the container, `swerex-remote` (installed via pipx) runs as a small
   server waiting for commands.
4. `SWEEnv.communicate(action, timeout)` sends commands to the remote server and
   receives stdout/stderr.
5. Tool bundles are installed into the container via their `install.sh` scripts.
6. The repository under test is cloned into the container's working directory.

### Deployment backends

| Backend          | Description                              |
|------------------|------------------------------------------|
| Docker (default) | Local container via Docker or Podman     |
| Modal            | Serverless function execution            |
| AWS Fargate      | Managed container service                |
| Daytona          | Development environment platform (WIP)   |
| Local            | Native shell on the host machine         |

### Custom Docker environments

Users can create custom Dockerfiles for specific testing needs:

```dockerfile
FROM python:3.11.10-bullseye
ARG DEBIAN_FRONTEND=noninteractive
RUN pip install swe-rex flake8
```

Then reference it in the CLI:

```bash
sweagent run --env.deployment.image swe-agent-custom ...
```

### SWE-bench integration

For SWE-bench evaluation, Docker images are automatically retrieved from Docker Hub.
Each SWE-bench instance has a pre-built image with the correct repository version,
dependencies, and test infrastructure already installed.

### Command execution details

- Commands are sent as `BashAction` objects with configurable timeouts.
- The default timeout is configurable per-command.
- After 5 consecutive `CommandTimeoutError` exceptions, the agent auto-submits its
  current patch and exits.
- Environment variables (see Section 4) are set at container startup to prevent
  interactive pagers and progress bars.

---

## 7. Evaluation — SWE-bench Integration

SWE-agent was designed hand-in-hand with the SWE-bench benchmark, and evaluation
is a first-class concern.

### SWE-bench overview

SWE-bench is a benchmark of real-world GitHub issues. Each instance consists of:
- A problem statement (issue description)
- A repository at a specific commit
- A test patch that validates whether the issue is resolved
- A gold patch (the actual fix, used for reference)

The agent must produce a patch that makes the failing test(s) pass.

### Performance trajectory

| Time Period      | SWE-agent Performance | Notes                              |
|------------------|-----------------------|------------------------------------|
| May 2024 (paper) | 12.5% on SWE-bench    | SOTA among open-source at the time |
| Aug 2024         | ~20% (leaderboard)    | With newer models                  |
| 2025+            | >40% (with Claude 4)  | Major improvements via model upgrades |

**SWE-bench Verified** (a human-validated subset of 500 instances) has become the
preferred evaluation set, with top agents achieving 70-80%+ pass@1 rates using the
latest frontier models.

### Evaluation workflow

1. **Batch mode**: `sweagent run-batch` processes multiple SWE-bench instances in
   parallel, leveraging SWE-ReX's multi-container support.
2. **Trajectory output**: Each run produces a `.traj` JSON file containing the full
   history, actions, observations, and model metadata.
3. **Patch extraction**: The final `git diff` is extracted as the agent's submission.
4. **Test validation**: The patch is applied to the repository and the test suite is
   run to check if the target test(s) pass.

### Trajectory analysis

Trajectory files enable detailed analysis of agent behavior:
- Which commands were used at each step
- How many steps were needed
- Where the agent got stuck
- Token/cost usage per instance

SWE-agent includes a **trajectory browser** for visualizing and inspecting runs.

### Behavioral patterns (from the paper)

- **Early turns**: Dominated by search/navigation (`find_file`, `search_dir`,
  `open`, `scroll_down`) for fault localization.
- **Later turns**: Shift to "edit, then execute" loops, with `edit` and `python`
  (bash) as the most frequent actions from turn 5 onwards.
- **Interspersed localization**: Even in later turns, agents frequently look at
  more code with `search_file`, `scroll_up/down`, or navigate to other files.

---

## 8. Model Support

SWE-agent supports any model available through LiteLLM, which provides a unified
API across dozens of LLM providers.

### Configuration

Model settings are specified in the YAML config under `agent.model`:

```yaml
# OpenAI
agent:
  model:
    name: gpt-4o
    temperature: 0.0

# Anthropic Claude
agent:
  model:
    name: claude-sonnet-4-20250514
    temperature: 0.0
    completion_kwargs: {}

# Anthropic with extended thinking
agent:
  model:
    name: claude-sonnet-4-20250514
    temperature: 1
    completion_kwargs:
      reasoning_effort: 'high'

# OpenAI o1
agent:
  model:
    name: o1
    temperature: 1
    completion_kwargs:
      top_p: null

# Ollama (local)
agent:
  model:
    name: ollama/llama2
    api_base: http://localhost:11434
```

### Provider support

| Provider     | Example Model ID                  | Notes                         |
|--------------|-----------------------------------|-------------------------------|
| OpenAI       | `gpt-4o`, `o1`, `o3-mini`        | Native function calling       |
| Anthropic    | `claude-sonnet-4-20250514`        | Prompt caching via history processor |
| AWS Bedrock  | `bedrock/anthropic.claude-...`    | Via LiteLLM Bedrock adapter   |
| Groq         | `groq/llama-3.1-70b`             | Fast inference                |
| Ollama       | `ollama/llama2`, `ollama/qwen2.5`| Local models                  |
| OpenRouter   | Via LiteLLM                       | Proxy to many providers       |
| Any LiteLLM  | `<provider>/<model>`              | Anything LiteLLM supports     |

### Anthropic prompt caching

For Claude models, the `cache_control` history processor marks recent messages for
caching:

```yaml
history_processors:
  - type: cache_control
    last_n_messages: 2
```

This significantly reduces costs by caching the system prompt and recent context.
Note: each API key supports only 4 cache breakpoints, limiting parallel instances
to 2 per key.

### Multi-key rotation

SWE-agent supports rotating across multiple API keys (separated by `:::`):

```
ANTHROPIC_API_KEY=key1:::key2:::key3
```

A thread-based rotation mechanism distributes requests across keys.

### Cost tracking and limits

`LiteLLMModel` provides automatic cost tracking at three levels:
- **Per-instance cost limit**: Max spend on a single problem
- **Total cost limit**: Max spend across all problems
- **Per-call-count limit**: Max number of API calls per instance

Custom model registries (JSON files) allow defining pricing for non-standard or
local models:

```yaml
litellm_model_registry: /path/to/custom_registry.json
```

### Action parsers and model compatibility

Different models require different action parsing strategies:

| Parser Type              | Config Value              | Best For                         |
|--------------------------|---------------------------|----------------------------------|
| `FunctionCallingParser`  | `function_calling`        | Models with native tool use (GPT-4, Claude) |
| `ThoughtActionParser`    | `thought_action`          | Models without function calling   |
| `XMLThoughtActionParser` | `xml_thought_action`      | XML-format-friendly models        |
| `XMLFunctionCallingParser`| `xml_function_calling`   | XML-based tool calling            |
| `JsonParser`             | `json`                    | JSON-output models                |
| `BashCodeBlockParser`    | `all_bash_code_blocks`    | Execute all ```bash blocks        |
| `SingleBashCodeBlockParser`| `single_bash_code_block`| Execute first ```bash block only  |
| `ActionParser`           | `action`                  | Single command, no discussion     |
| `ActionOnlyParser`       | `action_only`             | Minimal parsing                   |
| `EditFormat`             | `edit_format`             | Code editing scenarios            |
| `Identity`               | `identity`                | No parsing (pass-through)         |

When using a non-function-calling parser, tool documentation must be explicitly
included in the system prompt via `{{command_docs}}`.

### Test/development models

SWE-agent includes built-in models for testing without API costs:
- `HumanModel` — interactive human-in-the-loop
- `ReplayModel` — replays a recorded trajectory
- `InstantEmptySubmitTestModel` — immediately submits (for testing infrastructure)

---

## 9. History Processors and Context Management

History processors compress the conversation history before each model call to fit
within context window limits.

### Available processors

| Processor Type    | Description                                              |
|-------------------|----------------------------------------------------------|
| `cache_control`   | Marks last N messages with Anthropic cache control headers |
| (Default)         | Compresses older messages, keeps recent ~5 steps in full  |

### How compression works

The default approach keeps recent interactions (typically the last 5 steps) in full
detail while condensing older messages. This ensures the model always has access to
its most recent actions and observations while staying within token limits.

The `cache_control` processor is specifically designed for Anthropic's prompt caching
feature. It sets `cache_control` fields on the last N messages, which:
- Enables the API to cache and reuse the system prompt and early context
- Significantly reduces per-turn costs
- Must be removed when using non-Anthropic models (the fields would cause errors)

---

## 10. Comparison Notes — SWE-agent vs. a Minimal Custom Agent Loop

### Key strengths of SWE-agent

1. **ACI design philosophy**: The core insight — that constraining and optimizing
   the action space for LM consumption dramatically improves performance — is
   SWE-agent's most important contribution. The 10.7pp improvement over raw shell
   access is compelling evidence.

2. **Research-grade infrastructure**: Trajectory recording, batch evaluation,
   SWE-bench integration, and the trajectory browser make it excellent for
   systematic experimentation.

3. **Robust error recovery**: The multi-level error handling (format errors, syntax
   errors, cost limits, timeouts) with automatic requerying makes the agent loop
   resilient.

4. **Environment isolation**: The SWE-ReX abstraction provides clean separation
   between agent logic and execution infrastructure, with support for multiple
   deployment backends.

5. **Configurable and hackable**: The single-YAML-file configuration, pluggable
   tool bundles, and modular architecture make it easy to experiment with different
   ACI designs.

6. **Linter guardrails**: Preventing syntactically invalid edits is a simple but
   high-impact design choice that many agent frameworks lack.

### Key weaknesses / considerations

1. **Complexity**: The full SWE-agent codebase is substantial — far more than a
   minimal agent loop needs. The tool bundle system, SWE-ReX integration,
   trajectory recording, and configuration system add significant overhead.

2. **Docker dependency**: While SWE-ReX supports local execution, the default
   workflow requires Docker. This adds setup friction and may not be appropriate
   for all use cases.

3. **SWE-bench-centric**: The default configuration and templates are heavily
   optimized for SWE-bench-style tasks. Adapting to other domains requires
   significant configuration work.

4. **No native multi-agent support**: SWE-agent is a single-agent system. The
   `RetryAgent` provides multiple attempts but not true multi-agent collaboration.

5. **History compression is basic**: The default history processor uses simple
   truncation. More sophisticated approaches (semantic compression, hierarchical
   summaries) could improve long-horizon task performance.

### The ACI lesson for minimal agent loops

The most transferable insight from SWE-agent is the **ACI design philosophy**:

- **Do not expose raw shell access as the only interface.** Even if you support
  bash, provide structured tool definitions with clear documentation and
  constrained parameters.
- **Format observations for LM consumption.** Truncate long outputs, provide
  explicit no-output messages, and use consistent formatting.
- **Add guardrails.** Validate edits before applying them. Reject obviously broken
  actions. This costs almost nothing to implement but provides outsized benefits.
- **Control the viewport.** Do not dump entire files into context. Show manageable
  chunks and let the agent navigate.

### mini-swe-agent — The minimal counterpoint

The SWE-agent team also maintains **mini-swe-agent** (~100 lines of core Python),
which achieves >74% on SWE-bench Verified by making three deliberate simplifications:

1. **No specialized tools** — uses only bash (no custom ACI commands)
2. **Independent actions** — each action uses `subprocess.run` instead of a stateful
   shell session
3. **Linear message history** — no branching, no compression, fully transparent

mini-swe-agent demonstrates that with modern frontier models (Claude Sonnet 4,
GPT-4o), the model itself has become capable enough that the elaborate ACI may be
less necessary than it was in 2024. However, the ACI still provides clear benefits
for weaker models and for constraining failure modes.

---

## References

- [SWE-agent GitHub Repository](https://github.com/SWE-agent/SWE-agent)
- [SWE-agent Documentation](https://swe-agent.com/latest/)
- [SWE-agent Paper (arXiv)](https://arxiv.org/abs/2405.15793)
- [SWE-agent Paper (NeurIPS 2024 proceedings)](https://proceedings.neurips.cc/paper_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf)
- [SWE-agent ACI Background](https://swe-agent.com/latest/background/)
- [SWE-agent Agent Config Reference](https://swe-agent.com/latest/reference/agent_config/)
- [SWE-agent Agent Class Reference](https://swe-agent.com/latest/reference/agent/)
- [SWE-agent Tools Documentation](https://swe-agent.com/latest/config/tools/)
- [SWE-agent Templates Documentation](https://swe-agent.com/latest/config/templates/)
- [SWE-agent Models Documentation](https://swe-agent.com/latest/config/models/)
- [SWE-agent Environments Documentation](https://swe-agent.com/latest/config/environments/)
- [SWE-agent Action Parsers Reference](https://swe-agent.com/latest/reference/parsers/)
- [SWE-agent Architecture](https://swe-agent.com/latest/background/architecture/)
- [SWE-ReX GitHub Repository](https://github.com/SWE-agent/SWE-ReX)
- [mini-swe-agent GitHub Repository](https://github.com/SWE-agent/mini-swe-agent)
- [SWE-bench Leaderboard](https://www.swebench.com/)
- [Adding Custom Tools](https://swe-agent.com/latest/usage/adding_custom_tools/)
- [edit_anthropic config.yaml](https://github.com/SWE-agent/SWE-agent/blob/main/tools/edit_anthropic/config.yaml)
- [DeepWiki SWE-agent Overview](https://deepwiki.com/SWE-agent/SWE-agent)
