"""Best-effort shell command parser that extracts likely mutated file paths."""

from __future__ import annotations

import re
import shlex


def extract_mutated_paths(command: str) -> list[str]:
    """Return file paths that *command* is likely to create, modify, or delete.

    This is best-effort heuristic parsing — it will never raise.
    Returns ``[]`` when the command is read-only or unparseable.
    """
    try:
        return _extract(command)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Operators that split independent command segments.
_SEGMENT_SPLIT_RE = re.compile(r"\s*(?:\|\||&&|;)\s*")

# Redirect operators: >, >>, 1>, 2>, &>
_REDIRECT_RE = re.compile(r"(?:\d?>?>|&>>?)\s*(\S+)")

# Commands whose *arguments* are mutated paths.
_MUTATING_COMMANDS: dict[str, str] = {
    # Unix
    "rm": "all",
    "rmdir": "all",
    "touch": "all",
    "mkdir": "all",
    "chmod": "trailing",
    "chown": "trailing",
    "chgrp": "trailing",
    # Windows equivalents
    "del": "all",
}

# Commands where only the *last* argument is the destination (mutated).
_DEST_ONLY_COMMANDS = {"cp", "copy"}

# Commands where both source and destination are mutated.
_SRC_AND_DEST_COMMANDS = {"mv", "move"}


def _extract(command: str) -> list[str]:
    if not command or not command.strip():
        return []

    paths: list[str] = []

    # Split on chaining operators but keep pipe-right segments.
    segments = _split_segments(command)

    for segment in segments:
        paths.extend(_extract_from_segment(segment))

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _split_segments(command: str) -> list[str]:
    """Split *command* on ``|``, ``&&``, ``;``, and ``||``.

    For pipes (``|``) only the rightmost segment can mutate via redirect,
    but the ``tee`` command inside any segment can also write, so we return
    every segment for inspection.
    """
    # First split on ||, &&, ;
    parts = _SEGMENT_SPLIT_RE.split(command)
    # Then split each part further on single |
    segments: list[str] = []
    for part in parts:
        segments.extend(s.strip() for s in part.split("|") if s.strip())
    return segments


def _extract_from_segment(segment: str) -> list[str]:
    paths: list[str] = []

    # 1. Redirect targets (>, >>)
    for match in _REDIRECT_RE.finditer(segment):
        target = match.group(1).strip("'\"")
        if _is_valid_path(target):
            paths.append(target)

    # 2. Parse the command word + arguments
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        # Unbalanced quotes etc. — try a rough split.
        tokens = segment.split()

    if not tokens:
        return paths

    cmd = _base_command(tokens[0])
    args = _strip_flags(tokens[1:])

    # tee
    if cmd == "tee":
        for arg in args:
            if _is_valid_path(arg):
                paths.append(arg)
        return paths

    # sed -i
    if cmd == "sed" and _has_inplace_flag(tokens[1:]):
        # The file arguments follow the pattern/expression.
        # Heuristic: take the last N args that look like paths.
        for arg in reversed(args):
            if _is_valid_path(arg):
                paths.append(arg)
            else:
                break
        return paths

    # rm, rmdir, touch, mkdir, del, chmod, chown, chgrp
    mode = _MUTATING_COMMANDS.get(cmd)
    if mode == "all":
        for arg in args:
            if _is_valid_path(arg):
                paths.append(arg)
        return paths
    if mode == "trailing":
        # chmod/chown/chgrp: first real arg is the mode/owner, rest are paths.
        for arg in args[1:]:
            if _is_valid_path(arg):
                paths.append(arg)
        return paths

    # cp / copy — destination only
    if cmd in _DEST_ONLY_COMMANDS and len(args) >= 2:
        dest = args[-1]
        if _is_valid_path(dest):
            paths.append(dest)
        return paths

    # mv / move — source + destination
    if cmd in _SRC_AND_DEST_COMMANDS and len(args) >= 2:
        for arg in args:
            if _is_valid_path(arg):
                paths.append(arg)
        return paths

    return paths


def _base_command(token: str) -> str:
    """Return the base command name, stripping any leading path."""
    # Handle e.g. /usr/bin/rm → rm, C:\\Windows\\del → del
    name = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    # Strip .exe / .cmd / .bat suffix on Windows
    for suffix in (".exe", ".cmd", ".bat"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.lower()


def _strip_flags(args: list[str]) -> list[str]:
    """Remove flag-like tokens (``-x``, ``--foo``) from *args*."""
    return [a for a in args if not a.startswith("-")]


def _has_inplace_flag(args: list[str]) -> bool:
    """Check whether ``sed`` is invoked with an in-place flag."""
    for arg in args:
        if arg == "-i" or arg.startswith("-i"):
            return True
        if arg == "--in-place":
            return True
    return False


_DEV_NULL_NAMES = frozenset({"/dev/null", "nul", "NUL"})


def _is_valid_path(token: str) -> bool:
    """Return True if *token* looks like a real file path (not /dev/null, etc.)."""
    if not token or not token.strip():
        return False
    stripped = token.strip("'\"")
    if stripped.lower() in {s.lower() for s in _DEV_NULL_NAMES}:
        return False
    return True
