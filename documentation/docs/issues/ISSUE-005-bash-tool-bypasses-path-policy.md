# ISSUE-005: `bash` tool bypasses filesystem path policy

## Date

2026-05-06

## Status

**Open** — design decision needed before implementation.

## Summary

The `@micro-x-ai/mcp-filesystem` server enforces working-directory containment for `grep`, `glob`, `read_file`, `write_file`, and `append_file` via the `PathPolicy` helper (`paths.ts`), with extra roots opt-in via `FILESYSTEM_ALLOWED_DIRS`. The `bash` tool does not participate in this policy: it executes arbitrary shell commands with the server process's full filesystem permissions, so an agent can read or write anywhere via `bash` even when the policy would deny the same path through any other tool.

## Why this isn't a quick fix

A wrapper around `bash` cannot make it airtight. Any of the following defeat a string-level filter:

- Subshells: `cat $(echo /etc/passwd)`
- Variable expansion: `P=/etc/passwd; cat "$P"`
- Indirection: `bash -c 'cat /etc/passwd'`, `eval`, here-docs
- Encoded paths: base64 → decode → exec
- Command substitution rendering paths from arbitrary computation

Real containment for an arbitrary-shell tool is OS-level: containers, AppArmor/SELinux profiles, Windows Job Objects, dropped privileges, or chroot.

## Options considered

### Option A — Defense-in-depth wrapper (pragmatic, not airtight)

Add two layered, opt-in policies to `bash.ts`:

1. **Command allowlist** — `FILESYSTEM_BASH_ALLOWED_COMMANDS=git,npm,pytest,ls,cat`. If set, only commands whose first token matches are executed. Default: unset (all commands allowed — current behavior).
2. **Absolute-path escape scan** — `FILESYSTEM_BASH_PATH_GUARD=true`. Tokenize the command, find anything that looks like an absolute path, check it against `PathPolicy`, reject if outside allowed roots. Default: false.

**Pros:** non-breaking, catches accidents and casual escapes, gives the user a knob to tighten per environment.
**Cons:** trivially bypassable by a determined agent; risks giving false sense of security.

### Option B — Drop `bash`, replace with structured tools

Remove the `bash` tool. Add focused, structured-input tools that cover the actual use cases:

- `git_command` (subcommand allowlist: status, diff, log, add, commit, …)
- `run_tests` (selects a configured runner)
- `mkdir`, `mv`, `rm` (paths go through `PathPolicy`)
- `npm_run` / `package_script` (script-name allowlist)

**Pros:** real containment without needing OS sandboxing — every tool's inputs are policy-checked.
**Cons:** more tools to maintain; some current bash usage will need to be re-expressed.

### Option C — OS-level sandboxing

Run the filesystem MCP server inside a container or with platform-specific isolation (Job Object on Windows, AppArmor/seccomp on Linux). `bash` keeps its current shape.

**Pros:** real containment; covers tools we haven't written yet.
**Cons:** deployment complexity; non-trivial on Windows; out of scope for the MCP package itself.

## Recommendation

**Option A now, with prominent documentation that bash is not sandboxed**, plus tracking Option B as a follow-up if/when the bash escape hatch becomes a real risk (e.g., running untrusted prompts, multi-tenant use). Option C is the right answer for production deployment regardless of which tool surface ships.

## Acceptance criteria

When this issue is resolved:

- The `bash` tool's description explicitly states whether and how filesystem access is constrained.
- If Option A: the two env vars are documented in `documentation/docs/operations/` and the filesystem package README.
- If Option B: each replacement tool has an entry in `documentation/docs/design/`, and `bash` is removed from `index.ts`.
- If Option C: deployment docs in `documentation/docs/operations/` cover the chosen sandbox.

## Related

- `mcp_servers/ts/packages/filesystem/src/paths.ts` — the `PathPolicy` that `bash` currently bypasses.
- `mcp_servers/ts/packages/filesystem/src/tools/bash.ts` — the tool to revise or remove.
- The existing `read_file` / `write_file` / `append_file` tools are also not yet on `PathPolicy`. Migrating them is worth doing **alongside or after** this issue, not before — while `bash` is unconstrained, restricting the file tools is mostly cosmetic (the agent can do the same thing via `bash`). Note also that `write_file` / `append_file` are higher-risk than `grep` / `glob`, so the current asymmetry (search tools gated, write tools open) is backwards.

  **Migration shape (~15-line diff per tool, no design work):**

  Today each tool resolves paths inline, e.g. `read_file.ts:33-35`:

  ```ts
  const resolvedPath = path.isAbsolute(input.path)
    ? input.path
    : path.resolve(workingDir, input.path);
  ```

  Replace with one call into the existing helper:

  ```ts
  const resolvedPath = await resolveAllowed(policy, input.path, { mustExist: true });   // read_file
  const resolvedPath = await resolveAllowed(policy, input.path, { mustExist: false });  // write_file, append_file
  ```

  Tool signatures change from `(server, logger, workingDir: string)` to `(server, logger, policy: PathPolicy)`; `index.ts` passes `policy` instead of `workingDir`. `resolveAllowed` adds three things the inline code doesn't: `realpath` resolution (defeats symlink escape), containment check against `policy.workingDir + extraAllowed`, and a clear error message naming `FILESYSTEM_ALLOWED_DIRS` when denied.

  **Behavior change to flag in release notes:** absolute paths outside `FILESYSTEM_WORKING_DIR` (and not in `FILESYSTEM_ALLOWED_DIRS`) start failing. Today they silently succeed — any workflow relying on that needs the extra root added to `FILESYSTEM_ALLOWED_DIRS`.
