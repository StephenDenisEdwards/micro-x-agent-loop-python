"""Conversation-history repair utilities.

Anthropic rejects requests whose ``tool_use`` blocks are not followed by
matching ``tool_result`` blocks, or whose first message is a bare
``tool_result``. These helpers detect and repair those failure modes:

* ``find_safe_trim_count`` / ``repair_orphan_head`` — keep the head of the
  conversation in a shape Anthropic accepts after trimming or after
  loading a persisted session that may have been corrupted by older
  trim logic.
* ``find_tail_orphan_tool_use_ids`` / ``INTERRUPTED_TOOL_RESULT`` /
  ``repair_orphan_tool_uses`` — synthesise ``is_error: true`` tool_result
  blocks for ``tool_use`` blocks that were never answered (typical fallout
  from cancelling a run mid-tool).

All functions are pure: they take messages and return either the count of
work to do or a ``(repaired, count)`` tuple. They never mutate input.
"""

from __future__ import annotations

INTERRUPTED_TOOL_RESULT = (
    "Tool execution did not complete (interrupted, cancelled, or crashed). "
    "No result is available."
)


def is_safe_message_head(msg: dict) -> bool:
    """True if ``msg`` can safely sit at ``messages[0]`` of an Anthropic request:
    role is ``user`` and content is not solely ``tool_result`` blocks (whose
    matching ``tool_use`` would have been trimmed away).
    """
    if msg.get("role") != "user":
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") != "tool_result" for b in content)


def find_safe_trim_count(messages: list[dict], max_messages: int) -> int:
    """Return how many leading messages can be dropped to bring the list to
    at most ``max_messages`` without leaving an orphan ``tool_result`` at the
    head. Returns 0 when no safe boundary exists in the trim range.
    """
    if max_messages <= 0 or len(messages) <= max_messages:
        return 0
    target = len(messages) - max_messages
    safe = target
    while safe < len(messages) and not is_safe_message_head(messages[safe]):
        safe += 1
    if safe >= len(messages):
        return 0
    return safe


def repair_orphan_head(messages: list[dict]) -> tuple[list[dict], int]:
    """Drop leading messages from ``messages`` until the head is safe to send
    to Anthropic. Returns ``(repaired, dropped_count)``. Used after loading a
    persisted session that may have been corrupted by older trim logic.
    """
    drop = 0
    while drop < len(messages) and not is_safe_message_head(messages[drop]):
        drop += 1
    if drop == 0:
        return messages, 0
    return messages[drop:], drop


def find_tail_orphan_tool_use_ids(messages: list[dict]) -> list[str]:
    """Return any ``tool_use`` ids in the LAST message that lack a matching
    ``tool_result`` afterwards. The "tail orphan" pattern is the typical
    fallout from cancelling a run mid-tool: the assistant ``tool_use`` was
    appended, then tool execution was cancelled before the user
    ``tool_result`` could be appended.
    """
    if not messages:
        return []
    last = messages[-1]
    if last.get("role") != "assistant":
        return []
    content = last.get("content")
    if not isinstance(content, list):
        return []
    ids: list[str] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            bid = b.get("id")
            if isinstance(bid, str) and bid:
                ids.append(bid)
    return ids


def repair_orphan_tool_uses(messages: list[dict]) -> tuple[list[dict], int]:
    """Walk through ``messages`` and ensure every assistant ``tool_use`` block
    has a matching ``tool_result`` block in the immediately-following user
    message. Synthesises ``is_error: true`` tool_results for any orphans
    (typically left behind when tool execution was interrupted). Returns
    ``(repaired, inserted_count)``.

    Anthropic rejects the request if any ``tool_use`` is not followed by a
    matching ``tool_result``, so this repair runs both at session load and at
    the start of every ``run()`` to keep an interrupted prior turn from
    poisoning the next request.
    """
    repaired: list[dict] = []
    inserted = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        repaired.append(msg)
        if msg.get("role") != "assistant":
            i += 1
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            i += 1
            continue
        tool_use_ids = [
            b.get("id")
            for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        ]
        if not tool_use_ids:
            i += 1
            continue

        existing_result_ids: set[str] = set()
        next_idx = i + 1
        next_is_user_results = (
            next_idx < len(messages)
            and messages[next_idx].get("role") == "user"
            and isinstance(messages[next_idx].get("content"), list)
        )
        if next_is_user_results:
            for b in messages[next_idx]["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tid = b.get("tool_use_id")
                    if tid:
                        existing_result_ids.add(tid)

        missing = [tid for tid in tool_use_ids if tid not in existing_result_ids]
        if not missing:
            i += 1
            continue

        synthetic = [
            {
                "type": "tool_result",
                "tool_use_id": tid,
                "content": INTERRUPTED_TOOL_RESULT,
                "is_error": True,
            }
            for tid in missing
        ]
        if next_is_user_results:
            merged_content = list(messages[next_idx]["content"]) + synthetic
            repaired.append({"role": "user", "content": merged_content})
            inserted += len(synthetic)
            i += 2
        else:
            repaired.append({"role": "user", "content": synthetic})
            inserted += len(synthetic)
            i += 1
    return repaired, inserted
