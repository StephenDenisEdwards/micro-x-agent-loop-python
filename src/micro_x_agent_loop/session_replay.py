"""Session step-through reconstruction (PLAN-observability Phase 2).

``reconstruct_session`` turns the persisted record of a session — the ``events``
log (turn-tagged via the Phase 0 ``_meta`` correlation tuple), the ``messages``
history, and the ``tool_calls`` table — into a human-readable, turn-by-turn
timeline. It is the concrete realisation of the Phase 1 acceptance ("a script
can query ``memory.db`` and reconstruct turn-by-turn …") and the data source for
the ``/replay`` command.

The function is pure over a ``MemoryStore``: no agent, no I/O beyond SQLite, so
it is trivially testable and reusable as a standalone script.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from micro_x_agent_loop.memory.store import MemoryStore

_MAX_PREVIEW = 160


def _preview(text: str, limit: int = _MAX_PREVIEW) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _loads(raw: Any) -> dict:
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _turn_of(payload: dict) -> int:
    meta = payload.get("_meta")
    if isinstance(meta, dict):
        try:
            return int(meta.get("turn", 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _summarize_content(content: Any) -> str:
    """One-line summary of a message's ``content_json`` (str or block list)."""
    if isinstance(content, str):
        return _preview(content)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(_preview(str(block.get("text", "")), 100))
            elif btype == "tool_use":
                parts.append(f"⚙ tool_use {block.get('name', '?')}")
            elif btype == "tool_result":
                flag = " (error)" if block.get("is_error") else ""
                parts.append(f"↩ tool_result{flag}")
            else:
                parts.append(str(btype))
        return " | ".join(parts) if parts else "(empty)"
    return "(empty)"


# --- per-event-type renderers -------------------------------------------------


def _render_session_config(p: dict) -> list[str]:
    cfg = p.get("config", {})
    cfg_str = ", ".join(f"{k}={v}" for k, v in cfg.items()) if isinstance(cfg, dict) else ""
    return [
        f"  [config] code_sha={p.get('code_sha', '?')} config_hash={p.get('config_hash', '?')}",
        f"           {cfg_str}",
    ]


def _render_mode(p: dict) -> list[str]:
    signals = p.get("signals", [])
    sig_names = ",".join(s.get("name", "?") for s in signals if isinstance(s, dict)) if signals else "none"
    line = (
        f"  [mode] stage1={p.get('stage1_recommendation', '?')} "
        f"stage2={p.get('stage2_recommendation')} choice={p.get('user_choice')} signals=[{sig_names}]"
    )
    out = [line]
    if p.get("stage2_reasoning"):
        out.append(f"         reasoning: {_preview(str(p['stage2_reasoning']))}")
    return out


def _render_routing(p: dict) -> list[str]:
    line = (
        f"  [routing] task={p.get('task_type', '?')} stage={p.get('stage', '?')} "
        f"conf={p.get('confidence', '?')} policy={p.get('policy_name', '')} "
        f"→ {p.get('provider', '?')}/{p.get('model', '?')}"
    )
    flags = []
    if p.get("confidence_gate_triggered"):
        flags.append("confidence-gate")
    if p.get("pin_continuation_latched"):
        flags.append("pinned")
    if p.get("tool_search_only"):
        flags.append("tool-search-only")
    if p.get("system_prompt_compact"):
        flags.append("compact-prompt")
    if flags:
        line += f"  [{', '.join(flags)}]"
    return [line]


def _render_llm_call(p: dict, prompt_chars: dict[str, int], verbatim: _Verbatim | None = None) -> list[str]:
    tools = p.get("tool_names", [])
    tools_str = ",".join(tools) if isinstance(tools, list) else ""
    sha = str(p.get("system_prompt_sha256", ""))
    chars = p.get("system_prompt_chars") or prompt_chars.get(sha)
    lines = [
        f"  [llm.call] {p.get('call_type', '?')} → {p.get('effective_provider', '?')}/"
        f"{p.get('effective_model', '?')} temp={p.get('temperature', '?')} "
        f"max_tokens={p.get('max_tokens', '?')} msgs={p.get('message_count', '?')}",
        f"             prompt=sha:{sha[:8]}({chars} chars) tools=[{_preview(tools_str)}]",
    ]
    if verbatim is not None:
        lines.extend(verbatim.render(request_id=p.get("request_id"), system_prompt_sha=sha))
    return lines


def _render_api_metric(p: dict) -> list[str]:
    return [
        f"  [api] in={p.get('input_tokens', 0)} out={p.get('output_tokens', 0)} "
        f"cache_r={p.get('cache_read_input_tokens', 0)} ${p.get('estimated_cost_usd', 0):.4f} "
        f"{p.get('duration_ms', 0):.0f}ms stop={p.get('stop_reason', '?')}"
    ]


def _render_compaction(p: dict) -> list[str]:
    return [
        f"  [compaction] {p.get('estimated_tokens_before', 0)}→{p.get('estimated_tokens_after', 0)} tok "
        f"({p.get('messages_compacted', 0)} msgs, ${p.get('compaction_cost_usd', 0):.4f})"
    ]


class _Verbatim:
    """Loads the exact request snapshots for ``/replay --full`` expansion.

    The full system prompt is always available (``system_prompts`` table). The
    exact messages array + tool schemas are available only when
    ``ObservabilityVerbatimCapture`` was on for the run (``llm_requests`` /
    ``tool_schemas``). Secret values are redacted unless the run was captured
    under ``MICRO_X_OBSERVABILITY_UNREDACTED=1``.
    """

    def __init__(self, store: MemoryStore, session_id: str) -> None:
        self._prompt_text = {r["sha256"]: r["text"] for r in store.execute("SELECT sha256, text FROM system_prompts")}
        self._tools = {r["sha256"]: r["json"] for r in store.execute("SELECT sha256, json FROM tool_schemas")}
        self._requests = {
            r["id"]: dict(r)
            for r in store.execute(
                "SELECT id, system_prompt_sha256, tools_sha256, messages_json FROM llm_requests WHERE session_id = ?",
                (session_id,),
            )
        }

    def prompt_text(self, sha: str) -> str | None:
        return self._prompt_text.get(sha)

    def request(self, request_id: Any) -> dict | None:
        return self._requests.get(request_id) if request_id else None

    def tools(self, tools_sha: str) -> str | None:
        return self._tools.get(tools_sha)

    def render(self, *, request_id: Any, system_prompt_sha: str) -> list[str]:
        out: list[str] = ["    ── verbatim request ──"]
        prompt = self._prompt_text.get(system_prompt_sha)
        if prompt is not None:
            out.append("    SYSTEM PROMPT:")
            out.extend(f"      {ln}" for ln in prompt.splitlines() or [""])
        req = self._requests.get(request_id) if request_id else None
        if req is None:
            out.append("    (messages + tool schemas not captured — set ObservabilityVerbatimCapture=true)")
            return out
        out.append("    MESSAGES (verbatim):")
        out.extend(f"      {ln}" for ln in json.dumps(_loads_any(req["messages_json"]), indent=2).splitlines())
        tools_json = self._tools.get(req["tools_sha256"])
        if tools_json is not None:
            out.append("    TOOLS (verbatim):")
            out.extend(f"      {ln}" for ln in json.dumps(_loads_any(tools_json), indent=2).splitlines())
        return out


def _session_stream(store: MemoryStore, session_id: str) -> list[tuple[str, int, int, str, Any]]:
    """Merge events + messages + tool_calls into one chronological stream.

    Each item is ``(created_at, source_rank, ordinal, kind, data)``; ``source_rank``
    orders within-second ties so decisions precede output. Returns ``[]`` if the
    session has no persisted record.
    """
    stream: list[tuple[str, int, int, str, Any]] = []
    for i, row in enumerate(
        store.execute(
            "SELECT type, payload_json, created_at FROM events WHERE session_id = ? ORDER BY rowid",
            (session_id,),
        )
    ):
        stream.append((row["created_at"], 0, i, f"event:{row['type']}", _loads(row["payload_json"])))
    for i, row in enumerate(
        store.execute(
            "SELECT role, content_json, created_at FROM messages WHERE session_id = ? ORDER BY seq",
            (session_id,),
        )
    ):
        msg = {"role": row["role"], "content": _loads_any(row["content_json"])}
        stream.append((row["created_at"], 1, i, "message", msg))
    for i, row in enumerate(
        store.execute(
            "SELECT tool_name, input_json, result_text, is_error, was_truncated, original_chars, created_at "
            "FROM tool_calls WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        )
    ):
        stream.append((row["created_at"], 2, i, "tool_call", dict(row)))
    stream.sort(key=lambda e: (e[0], e[1], e[2]))
    return stream


def reconstruct_session(store: MemoryStore, session_id: str, *, full: bool = False) -> list[str]:
    """Reconstruct *session_id* as a turn-by-turn timeline of rendered lines.

    When *full* is true, each ``llm.call`` is expanded with the verbatim request
    (exact system prompt + messages + tool schemas) where available.

    Raises ``ValueError`` if the session has no persisted record at all.
    """
    verbatim = _Verbatim(store, session_id) if full else None
    # System-prompt sizes (for llm.call rows whose own chars field is absent).
    prompt_chars: dict[str, int] = {
        row["sha256"]: row["chars"] for row in store.execute("SELECT sha256, chars FROM system_prompts")
    }

    stream = _session_stream(store, session_id)
    if not stream:
        raise ValueError(f"No persisted record for session {session_id!r}")

    lines: list[str] = [f"═══ Session {session_id} ═══"]
    current_turn = -1

    def _ensure_turn_header(turn: int) -> None:
        nonlocal current_turn
        if turn != current_turn and turn > 0:
            current_turn = turn
            lines.append(f"── Turn {turn} ──")

    for _created_at, _rank, _ord, kind, data in stream:
        if kind.startswith("event:"):
            etype = kind.split(":", 1)[1]
            _ensure_turn_header(_turn_of(data))
            if etype == "session.config":
                lines.extend(_render_session_config(data))
            elif etype == "mode.analyzed":
                lines.extend(_render_mode(data))
            elif etype == "routing.decision":
                lines.extend(_render_routing(data))
            elif etype == "llm.call":
                lines.extend(_render_llm_call(data, prompt_chars, verbatim))
            elif etype == "metric.api_call":
                lines.extend(_render_api_metric(data))
            elif etype == "metric.compaction":
                lines.extend(_render_compaction(data))
            # Other event types (tool.*, metric.tool_execution, subagent.*) are
            # represented by the tool_calls / message rows below; skip to avoid noise.
        elif kind == "message":
            role = data.get("role", "?")
            lines.append(f"  [{role}] {_summarize_content(data.get('content'))}")
        elif kind == "tool_call":
            trunc = ""
            if data.get("was_truncated"):
                trunc = f" (truncated {data.get('original_chars')}→{len(data.get('result_text', ''))} chars)"
            err = " ✗error" if data.get("is_error") else ""
            tool_input = _loads_any(data.get("input_json"))
            lines.append(
                f"  [tool] {data.get('tool_name', '?')}({_preview(json.dumps(tool_input, default=str), 80)})"
                f"{err}{trunc}"
            )
            lines.append(f"         → {_preview(str(data.get('result_text', '')))}")

    return lines


def _loads_any(raw: Any) -> Any:
    """Parse JSON that may be a str, list, or dict; fall back to the raw value."""
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# Structured model — drives the TUI trace tree + detail panel.
# ---------------------------------------------------------------------------


@dataclass
class EventNode:
    """One selectable event in a turn. ``detail_md`` is Markdown for the panel."""

    kind: str  # config | mode | routing | llm_call | api | tool | compaction | message
    label: str  # short label for the tree node
    detail_md: str


@dataclass
class TurnNode:
    number: int  # 0 = session-level preamble (config etc.)
    label: str
    events: list[EventNode] = field(default_factory=list)


@dataclass
class SessionModel:
    session_id: str
    turns: list[TurnNode] = field(default_factory=list)


def _fence(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```"


def _json_block(value: Any) -> str:
    return _fence(json.dumps(value, indent=2, default=str), "json")


def _detail_config(p: dict) -> str:
    cfg = p.get("config", {})
    body = [f"**code_sha:** `{p.get('code_sha', '?')}`", f"**config_hash:** `{p.get('config_hash', '?')}`", ""]
    body.append(_json_block(cfg))
    return "\n".join(body)


def _detail_mode(p: dict) -> str:
    out = [
        f"**stage1:** {p.get('stage1_recommendation', '?')}",
        f"**stage2:** {p.get('stage2_recommendation')}",
        f"**choice:** {p.get('user_choice')}",
    ]
    if p.get("stage2_reasoning"):
        out.append(f"\n**reasoning:** {p['stage2_reasoning']}")
    if p.get("signals"):
        out.append("\n**signals:**")
        out.append(_json_block(p["signals"]))
    return "\n".join(out)


def _detail_routing(p: dict) -> str:
    flags = [
        name
        for name, key in (
            ("confidence-gate", "confidence_gate_triggered"),
            ("pinned", "pin_continuation_latched"),
            ("tool-search-only", "tool_search_only"),
            ("compact-prompt", "system_prompt_compact"),
        )
        if p.get(key)
    ]
    return "\n".join(
        [
            f"**task_type:** {p.get('task_type', '?')}",
            f"**stage:** {p.get('stage', '?')}  **confidence:** {p.get('confidence', '?')}",
            f"**policy:** {p.get('policy_name', '')}",
            f"**→** {p.get('provider', '?')}/{p.get('model', '?')}",
            f"**reason:** {p.get('reason', '')}",
            f"**flags:** {', '.join(flags) if flags else '—'}",
        ]
    )


def _detail_api(p: dict) -> str:
    return "\n".join(
        [
            f"**in:** {p.get('input_tokens', 0)}  **out:** {p.get('output_tokens', 0)}  "
            f"**cache_read:** {p.get('cache_read_input_tokens', 0)}",
            f"**cost:** ${p.get('estimated_cost_usd', 0):.4f}  **duration:** {p.get('duration_ms', 0):.0f}ms",
            f"**stop_reason:** {p.get('stop_reason', '?')}  **call_type:** {p.get('call_type', '?')}",
        ]
    )


def _detail_compaction(p: dict) -> str:
    return (
        f"**{p.get('estimated_tokens_before', 0)} → {p.get('estimated_tokens_after', 0)} tokens**\n\n"
        f"messages compacted: {p.get('messages_compacted', 0)}  cost: ${p.get('compaction_cost_usd', 0):.4f}"
    )


def _detail_llm_call(p: dict, verbatim: _Verbatim) -> str:
    sha = str(p.get("system_prompt_sha256", ""))
    out = [
        f"**{p.get('call_type', '?')} → {p.get('effective_provider', '?')}/{p.get('effective_model', '?')}**",
        f"temperature={p.get('temperature', '?')}  max_tokens={p.get('max_tokens', '?')}  "
        f"messages={p.get('message_count', '?')}",
        f"tools: {', '.join(p.get('tool_names', []) or [])}",
        "",
    ]
    prompt = verbatim.prompt_text(sha)
    if prompt is not None:
        out += [f"### System prompt  `sha:{sha[:8]}`", _fence(prompt)]
    req = verbatim.request(p.get("request_id"))
    if req is None:
        out.append("_Messages + tool schemas not captured — set ObservabilityVerbatimCapture=true._")
    else:
        out += ["### Messages (verbatim)", _json_block(_loads_any(req["messages_json"]))]
        tools_json = verbatim.tools(req["tools_sha256"])
        if tools_json is not None:
            out += ["### Tools (verbatim)", _json_block(_loads_any(tools_json))]
    return "\n".join(out)


def _detail_tool(d: dict) -> str:
    out = [f"**{d.get('tool_name', '?')}**"]
    if d.get("is_error"):
        out.append("⚠️ **error**")
    if d.get("was_truncated"):
        out.append(f"_truncated {d.get('original_chars')} → {len(d.get('result_text', ''))} chars_")
    out += ["", "**Input:**", _json_block(_loads_any(d.get("input_json")))]
    out += ["", "**Result:**", _fence(str(d.get("result_text", "")))]
    return "\n".join(out)


def _detail_message(d: dict) -> str:
    content = d.get("content")
    if isinstance(content, str):
        return content
    return _json_block(content)


def build_session_model(store: MemoryStore, session_id: str) -> SessionModel:
    """Build a structured turn/event model of a session for the trace tree.

    Always loads full detail (system prompt text + verbatim request where
    captured) — the detail panel is where the operator wants everything.
    Raises ``ValueError`` if the session has no persisted record.
    """
    stream = _session_stream(store, session_id)
    if not stream:
        raise ValueError(f"No persisted record for session {session_id!r}")
    verbatim = _Verbatim(store, session_id)

    model = SessionModel(session_id=session_id)
    turns: dict[int, TurnNode] = {}

    def _turn(n: int) -> TurnNode:
        if n not in turns:
            turns[n] = TurnNode(number=n, label="Session preamble" if n == 0 else f"Turn {n}")
            model.turns.append(turns[n])
        return turns[n]

    current = 0
    for _created_at, _rank, _ord, kind, data in stream:
        if kind.startswith("event:"):
            etype = kind.split(":", 1)[1]
            current = _turn_of(data) or current
            node = _event_node(etype, data, verbatim)
            if node is not None:
                _turn(current).events.append(node)
        elif kind == "message":
            role = str(data.get("role", "?"))
            _turn(current).events.append(
                EventNode("message", f"{role}: {_summarize_content(data.get('content'))}", _detail_message(data))
            )
        elif kind == "tool_call":
            name = data.get("tool_name", "?")
            _turn(current).events.append(EventNode("tool", f"tool: {name}", _detail_tool(data)))

    model.turns.sort(key=lambda t: t.number)
    return model


def _event_node(etype: str, data: dict, verbatim: _Verbatim) -> EventNode | None:
    if etype == "session.config":
        return EventNode("config", "config", _detail_config(data))
    if etype == "mode.analyzed":
        label = f"mode: {data.get('user_choice') or data.get('stage1_recommendation', '?')}"
        return EventNode("mode", label, _detail_mode(data))
    if etype == "routing.decision":
        return EventNode("routing", f"routing: {data.get('task_type', '?')}", _detail_routing(data))
    if etype == "llm.call":
        return EventNode(
            "llm_call",
            f"llm.call: {data.get('call_type', '?')} → {data.get('effective_model', '?')}",
            _detail_llm_call(data, verbatim),
        )
    if etype == "metric.api_call":
        label = f"api: ${data.get('estimated_cost_usd', 0):.4f} {data.get('duration_ms', 0):.0f}ms"
        return EventNode("api", label, _detail_api(data))
    if etype == "metric.compaction":
        return EventNode("compaction", "compaction", _detail_compaction(data))
    return None
