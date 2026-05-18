"""PathPolicy — faithful Python port of mcp_servers/ts/.../filesystem/src/paths.ts.

Containment for the native filesystem tools: every path is resolved
(symlinks included) and must sit inside the working dir, an extra allowed
dir, or a readonly dir; mutating ops are additionally rejected inside
readonly roots. Symlink-escape is defended by comparing *realpaths*.

Behaviour matches the TS original exactly, including:
- list parsing (os.pathsep split, trim, drop empties, abspath each),
- Node `fs.realpath` throws on a missing path → here `realpath(strict=True)`,
  with the "existing ancestor" walk for the mustExist=False case,
- Windows case-insensitive containment,
- the exact error-message strings (callers/tests/logs depend on them).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_IS_WINDOWS = os.name == "nt"


class PathPolicyError(Exception):
    """Raised when a path is outside allowed roots or violates readonly."""


@dataclass
class PathPolicy:
    working_dir: str
    extra_allowed: list[str] = field(default_factory=list)
    readonly: list[str] = field(default_factory=list)


def _parse_list(env: str | None) -> list[str]:
    if not env:
        return []
    return [
        os.path.abspath(p.strip())
        for p in env.split(os.pathsep)
        if p.strip()
    ]


def load_path_policy(
    working_dir: str,
    allowed_dirs_env: str | None,
    readonly_dirs_env: str | None = None,
) -> PathPolicy:
    return PathPolicy(
        working_dir=os.path.abspath(working_dir),
        extra_allowed=_parse_list(allowed_dirs_env),
        readonly=_parse_list(readonly_dirs_env),
    )


def _is_inside(target: str, root: str) -> bool:
    t = target.lower() if _IS_WINDOWS else target
    r = root.lower() if _IS_WINDOWS else root
    if t == r:
        return True
    r_with_sep = r if r.endswith(os.sep) else r + os.sep
    return t.startswith(r_with_sep)


def _realpath_strict(p: str) -> str:
    """os.path.realpath that raises (like Node fs.realpath) if p is missing."""
    return os.path.realpath(p, strict=True)


def _realpath_or(p: str) -> str:
    """Realpath, falling back to p itself if it cannot be resolved
    (mirrors TS `realpath(root).catch(() => root)`)."""
    try:
        return _realpath_strict(p)
    except OSError:
        return p


def _realpath_existing_ancestor(p: str) -> str:
    """Resolve the longest existing ancestor of p, then re-join the
    non-existent tail (port of TS realpathExistingAncestor)."""
    current = p
    tail: list[str] = []
    while True:
        try:
            real = _realpath_strict(current)
            if tail:
                return os.path.join(real, *reversed(tail))
            return real
        except OSError:
            parent = os.path.dirname(current)
            if parent == current:
                return p
            tail.append(os.path.basename(current))
            current = parent


def resolve_allowed(
    policy: PathPolicy,
    input_path: str | None,
    *,
    must_exist: bool = True,
) -> str:
    """Resolve ``input_path`` (relative to working_dir if not absolute),
    follow symlinks, and return the realpath iff it is inside an allowed
    root. Raises PathPolicyError otherwise."""
    raw = input_path if input_path is not None else policy.working_dir
    if os.path.isabs(raw):
        resolved = os.path.abspath(raw)
    else:
        resolved = os.path.abspath(os.path.join(policy.working_dir, raw))

    real = _realpath_strict(resolved) if must_exist else _realpath_existing_ancestor(resolved)

    roots = [policy.working_dir, *policy.extra_allowed, *policy.readonly]
    for root in roots:
        if _is_inside(real, _realpath_or(root)):
            return real

    allowed = "\n".join(f"  - {r}" for r in roots)
    raise PathPolicyError(
        f'Path "{raw}" is outside the allowed roots. Allowed:\n{allowed}\n'
        f'(set FILESYSTEM_ALLOWED_DIRS to add more, separated by "{os.pathsep}")'
    )


def require_writable(policy: PathPolicy, resolved: str) -> None:
    """Reject a resolved path that lies inside any readonly root."""
    if not policy.readonly:
        return
    for root in policy.readonly:
        if _is_inside(resolved, _realpath_or(root)):
            raise PathPolicyError(
                f'Path "{resolved}" is in a read-only root ({root}). '
                f"Mutating operations (write_file, append_file, edit_file, "
                f"delete_file) are not permitted here."
            )


def is_path_allowed(policy: PathPolicy, candidate: str) -> bool:
    try:
        resolve_allowed(policy, candidate, must_exist=False)
        return True
    except PathPolicyError:
        return False
