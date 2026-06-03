"""PII / secret redaction for the observability persistence path (Phase 3).

Redaction is applied to the *observability copies* of data — the ``events`` log,
the ``tool_calls`` audit record, and the deduped ``system_prompts`` table — never
to the live ``messages`` table. The messages table is the working conversation
that is replayed into the model on session resume; scrubbing it would feed the
model ``[REDACTED]`` in place of real history and corrupt the session. True
multi-tenant message redaction needs a separate export pipeline (out of scope).

``RegexRedactor.redact`` walks an arbitrary str/dict/list structure and replaces
matches of a secret-pattern set with a placeholder. A *field allowlist* names
dict keys whose values are known-safe (hashes, model ids, token counts) and are
skipped to avoid mangling them.
"""

from __future__ import annotations

import os
import re
from typing import Any, Protocol, runtime_checkable

_PLACEHOLDER = "[REDACTED]"

# Conservative, high-signal secret patterns — tuned to avoid scrubbing ordinary
# prose. Each is a (name, compiled-regex) pair; order does not matter.
_DEFAULT_PATTERNS: list[tuple[str, str]] = [
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openai_key", r"sk-[A-Za-z0-9]{20,}"),
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    ("google_api_key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("github_token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("slack_token", r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("jwt", r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    ("bearer", r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    # key=value / "key": "value" for sensitive key names
    (
        "secret_assignment",
        r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|token)\s*[=:]\s*[\"']?[^\s\"',}]{6,}",
    ),
]

# Dict keys whose values are structurally safe — never secrets — so we skip them
# (both to save work and to avoid e.g. a sha256 tripping a token pattern).
_DEFAULT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "system_prompt_sha256",
        "sha256",
        "config_hash",
        "code_sha",
        "model",
        "effective_model",
        "provider",
        "effective_provider",
        "call_type",
        "task_type",
        "tool_name",
        "role",
        "stage",
        "_meta",
    }
)


@runtime_checkable
class Redactor(Protocol):
    def redact(self, value: Any) -> Any: ...


class NullRedactor:
    """Pass-through redactor — used when redaction is disabled or unredacted mode is on."""

    def redact(self, value: Any) -> Any:
        return value


class RegexRedactor:
    """Recursively scrub secrets from str/dict/list structures."""

    def __init__(
        self,
        patterns: list[tuple[str, str]] | None = None,
        *,
        allowlist: frozenset[str] | None = None,
        placeholder: str = _PLACEHOLDER,
    ) -> None:
        pats = patterns if patterns is not None else _DEFAULT_PATTERNS
        self._regexes = [re.compile(p) for _, p in pats]
        self._allowlist = allowlist if allowlist is not None else _DEFAULT_ALLOWLIST
        self._placeholder = placeholder

    def _scrub_str(self, text: str) -> str:
        for rx in self._regexes:
            text = rx.sub(self._placeholder, text)
        return text

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._scrub_str(value)
        if isinstance(value, dict):
            return {k: (v if k in self._allowlist else self.redact(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self.redact(v) for v in value)
        return value


def build_redactor(config: dict | None, *, unredacted_env: str = "MICRO_X_OBSERVABILITY_UNREDACTED") -> Redactor:
    """Build a redactor from an ``ObservabilityRedaction`` config block + env override.

    The env flag is an explicit incident-response escape hatch: setting
    ``MICRO_X_OBSERVABILITY_UNREDACTED=1`` forces a ``NullRedactor`` regardless of
    config, so an operator can capture unredacted traces during an investigation.

    Config keys (all optional):
      - ``Enabled`` (bool, default True) — master switch.
      - ``ExtraPatterns`` (list[str]) — additional regexes appended to the defaults.
      - ``FieldAllowlist`` (list[str]) — extra dict keys to skip.
    """
    if os.environ.get(unredacted_env, "").strip() in ("1", "true", "True"):
        return NullRedactor()

    cfg = config or {}
    if not bool(cfg.get("Enabled", True)):
        return NullRedactor()

    patterns = list(_DEFAULT_PATTERNS)
    extra = cfg.get("ExtraPatterns")
    if isinstance(extra, list):
        for i, pat in enumerate(extra):
            if isinstance(pat, str) and pat:
                patterns.append((f"extra_{i}", pat))

    allowlist = set(_DEFAULT_ALLOWLIST)
    extra_allow = cfg.get("FieldAllowlist")
    if isinstance(extra_allow, list):
        allowlist.update(str(k) for k in extra_allow)

    return RegexRedactor(patterns, allowlist=frozenset(allowlist))
