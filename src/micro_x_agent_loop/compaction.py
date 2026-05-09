from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from micro_x_agent_loop.provider import LLMCompactor

import tiktoken
from loguru import logger

from micro_x_agent_loop.constants import (
    COMPACTION_PREVIEW_HEAD,
    COMPACTION_PREVIEW_TAIL,
    COMPACTION_PREVIEW_TOTAL,
    COMPACTION_SUMMARIZE_HALF_CAP,
    COMPACTION_SUMMARIZE_INPUT_CAP,
    DEFAULT_COMPACTION_THRESHOLD_TOKENS,
    DEFAULT_PROTECTED_TAIL_MESSAGES,
)
from micro_x_agent_loop.usage import UsageResult

_encoding = tiktoken.get_encoding("cl100k_base")


# Tool results carried verbatim through compaction. These are tools whose results
# are deterministic, content-bearing, and explicitly fetched by the model — the
# model usually wants the exact bytes back (quote a line, feed into edit_file,
# etc.). Summarising them defeats the purpose, breaks the read -> edit_file
# workflow, and forces a re-read if the content is needed again.
#
# Tools NOT on this list (bash, web fetch, sub-agent results) get summarised
# normally — their outputs can be huge and undirected, so summarisation is the
# right move.
_VERBATIM_TOOL_NAMES: set[str] = {
    "read_file",
    "filesystem__read_file",
    "grep",
    "filesystem__grep",
    "glob",
    "filesystem__glob",
}


@runtime_checkable
class CompactionStrategy(Protocol):
    async def maybe_compact(self, messages: list[dict]) -> list[dict]: ...


class NoneCompactionStrategy:
    async def maybe_compact(self, messages: list[dict]) -> list[dict]:
        return messages


class SummarizeCompactionStrategy:
    def __init__(
        self,
        provider: LLMCompactor,
        model: str,
        threshold_tokens: int = DEFAULT_COMPACTION_THRESHOLD_TOKENS,
        protected_tail_messages: int = DEFAULT_PROTECTED_TAIL_MESSAGES,
        on_compaction_completed: Callable[[UsageResult, int, int, int], None] | None = None,
        smart_trigger_enabled: bool = False,
    ):
        self._provider: LLMCompactor = provider
        self._model = model
        self._threshold_tokens = threshold_tokens
        self._protected_tail_messages = protected_tail_messages
        self._on_compaction_completed = on_compaction_completed
        self._smart_trigger_enabled = smart_trigger_enabled
        self._last_actual_input_tokens: int | None = None

    def update_actual_tokens(self, input_tokens: int) -> None:
        """Feed actual API-reported input token count for smart compaction triggering."""
        self._last_actual_input_tokens = input_tokens

    async def maybe_compact(self, messages: list[dict]) -> list[dict]:
        if self._smart_trigger_enabled and self._last_actual_input_tokens is not None:
            estimated = self._last_actual_input_tokens
        else:
            estimated = estimate_tokens(messages)
        if estimated < self._threshold_tokens:
            return messages

        if len(messages) < 2:
            return messages

        compact_start = 1
        compact_end = len(messages) - self._protected_tail_messages

        if compact_end <= compact_start:
            return messages

        compact_end = _adjust_boundary(messages, compact_start, compact_end)

        if compact_end <= compact_start:
            return messages

        # Identify verbatim message pairs in the compactable range. These will
        # be carried through the compaction unchanged — only the non-verbatim
        # messages get summarised.
        verbatim_indices = _find_verbatim_indices(messages, compact_start, compact_end)
        verbatim_set = set(verbatim_indices)
        summarisable = [
            messages[i] for i in range(compact_start, compact_end) if i not in verbatim_set
        ]

        compactable_count = compact_end - compact_start

        if not summarisable:
            logger.info(
                f"Compaction: all {compactable_count} compactable messages are verbatim"
                f" tool results (read_file/grep/glob) — skipping summarisation"
            )
            return messages

        verbatim_msgs = [messages[i] for i in verbatim_indices]

        logger.info(
            f"Compaction: estimated ~{estimated:,} tokens, threshold {self._threshold_tokens:,}"
            f" — compacting {len(summarisable)} of {compactable_count} messages"
            f" ({len(verbatim_msgs)} verbatim tool-result messages preserved)"
        )

        try:
            summary, usage = await _summarize(self._provider, self._model, summarisable)
        except Exception as ex:
            logger.warning(f"Compaction failed: {ex}. Falling back to history trimming.")
            return messages

        result = _rebuild_messages(messages, compact_end, summary, verbatim_msgs)

        tokens_after = estimate_tokens(result)
        summary_tokens = len(_encoding.encode(summary))
        freed = estimated - tokens_after
        logger.info(
            f"Compaction: summarized {len(summarisable)} messages into ~{summary_tokens:,} tokens,"
            f" preserved {len(verbatim_msgs)} verbatim, freed ~{freed:,} estimated tokens"
        )

        if self._on_compaction_completed is not None:
            self._on_compaction_completed(usage, estimated, tokens_after, compactable_count)

        return result


def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(_encoding.encode(content))
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    total += len(_encoding.encode(block))
                elif isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        total += len(_encoding.encode(block.get("text", "")))
                    elif block_type == "tool_use":
                        total += len(_encoding.encode(block.get("name", "")))
                        total += len(_encoding.encode(json.dumps(block.get("input", {}))))
                    elif block_type == "tool_result":
                        result_content = block.get("content", "")
                        if isinstance(result_content, str):
                            total += len(_encoding.encode(result_content))
                        elif isinstance(result_content, list):
                            for sub in result_content:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    total += len(_encoding.encode(sub.get("text", "")))
    return total


def _format_for_summarization(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, str):
            parts.append(f"[{role}]: {content}")
        elif isinstance(content, list):
            block_texts = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        block_texts.append(block.get("text", ""))
                    elif block_type == "tool_use":
                        name = block.get("name", "")
                        inp = json.dumps(block.get("input", {}), indent=None)
                        if len(inp) > 200:
                            inp = inp[:200] + "..."
                        block_texts.append(f"[Tool call: {name}({inp})]")
                    elif block_type == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, str):
                            preview = _preview_text(result_content)
                        elif isinstance(result_content, list):
                            text_parts = [
                                sub.get("text", "")
                                for sub in result_content
                                if isinstance(sub, dict) and sub.get("type") == "text"
                            ]
                            preview = _preview_text("\n".join(text_parts))
                        else:
                            preview = str(result_content)
                        block_texts.append(f"[Tool result ({tool_id})]: {preview}")
            parts.append(f"[{role}]: " + "\n".join(block_texts))

    return "\n\n".join(parts)


def _preview_text(text: str) -> str:
    if len(text) <= COMPACTION_PREVIEW_TOTAL:
        return text
    return text[:COMPACTION_PREVIEW_HEAD] + "\n[...truncated...]\n" + text[-COMPACTION_PREVIEW_TAIL:]


_SUMMARIZE_PROMPT = """\
Summarize the following conversation history between a user and an AI assistant.
Preserve these details precisely:
- The original user request and any specific criteria or instructions
- All decisions made and their reasoning
- Key data points, URLs, file paths, and identifiers that may be needed later
- Any scores, rankings, or evaluations produced
- Current task status and next steps

Do NOT include raw tool output data (job descriptions, email bodies, etc.) —
just note what was retrieved and key findings.

NOTE: file-read tool results (read_file, grep, glob) are preserved verbatim
outside this summary — you do not need to repeat their contents. Just note
which files were read and what was being looked for.

Format as a concise narrative summary.

---
CONVERSATION HISTORY:

"""


async def _summarize(
    provider: LLMCompactor,
    model: str,
    messages: list[dict],
) -> tuple[str, UsageResult]:
    formatted = _format_for_summarization(messages)

    # Cap summarization input
    if len(formatted) > COMPACTION_SUMMARIZE_INPUT_CAP:
        half = COMPACTION_SUMMARIZE_HALF_CAP
        formatted = formatted[:half] + "\n\n[...middle of conversation omitted for brevity...]\n\n" + formatted[-half:]

    logger.debug(f"Compaction API request: model={model}, input_chars={len(formatted):,}")
    text, usage = await provider.create_message(
        model,
        4096,
        0,
        [{"role": "user", "content": _SUMMARIZE_PROMPT + formatted}],
    )
    return text, usage


def _has_verbatim_tool_use(msg: dict) -> bool:
    """True if this assistant message contains any tool_use block whose name
    is in ``_VERBATIM_TOOL_NAMES``. A single verbatim call anchors the whole
    message — mixed batches (e.g. read_file + edit_file in one response) are
    treated as verbatim too, which is harmless because the non-verbatim
    results in the same batch are tiny status strings.
    """
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content", [])
    if not isinstance(content, list):
        return False
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name", "") in _VERBATIM_TOOL_NAMES
        ):
            return True
    return False


def _is_user_tool_result_message(msg: dict) -> bool:
    """True if this user message contains only ``tool_result`` blocks (the
    typical post-tool-use message).
    """
    if msg.get("role") != "user":
        return False
    content = msg.get("content", [])
    if not isinstance(content, list) or not content:
        return False
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            return False
    return True


def _find_verbatim_indices(messages: list[dict], start: int, end: int) -> list[int]:
    """Indices in ``[start, end)`` whose messages should survive compaction
    verbatim. Returns the assistant tool_use messages that contain at least
    one verbatim tool call, plus the immediately-following user tool_result
    messages they pair with.
    """
    verbatim: list[int] = []
    i = start
    while i < end:
        if _has_verbatim_tool_use(messages[i]):
            verbatim.append(i)
            if i + 1 < end and _is_user_tool_result_message(messages[i + 1]):
                verbatim.append(i + 1)
                i += 2
                continue
        i += 1
    return verbatim


def _adjust_boundary(messages: list[dict], start: int, end: int) -> int:
    while end > start + 1:
        boundary_msg = messages[end - 1]
        if boundary_msg.get("role") != "assistant":
            break
        content = boundary_msg.get("content", [])
        if not isinstance(content, list):
            break
        has_tool_use = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        if not has_tool_use:
            break
        # This assistant message has tool_use — its tool_result is at messages[end],
        # which would be in the protected tail. Pull boundary back.
        end -= 1

    return end


def _rebuild_messages(
    messages: list[dict],
    compact_end: int,
    summary: str,
    verbatim_msgs: list[dict] | None = None,
) -> list[dict]:
    first_msg = messages[0]
    original_content = first_msg.get("content", "")
    if isinstance(original_content, list):
        # Extract text from content blocks
        text_parts = [b.get("text", "") for b in original_content if isinstance(b, dict) and b.get("type") == "text"]
        original_content = "\n".join(text_parts)

    merged_content = original_content + "\n\n[CONTEXT SUMMARY]\n" + summary + "\n[END CONTEXT SUMMARY]"
    merged_first = {"role": "user", "content": merged_content}

    verbatim_msgs = verbatim_msgs or []
    tail = messages[compact_end:]

    result: list[dict] = [merged_first]

    # Insert verbatim tool-result pairs (assistant tool_use + user tool_result)
    # in chronological order. They alternate naturally so no role-fixup is
    # needed within the verbatim block. The merged_first is role=user, and
    # verbatim_msgs[0] (when present) is always role=assistant by construction
    # in _find_verbatim_indices.
    result.extend(verbatim_msgs)

    # Role alternation between the last item in `result` and the first item
    # in `tail`. The last item is either merged_first (user) or the final
    # verbatim msg (user — verbatim pairs end with the tool_result). Either
    # way the next item must be assistant; if tail[0] is user, insert an ack.
    if tail and tail[0].get("role") == result[-1].get("role"):
        if result[-1].get("role") == "user":
            result.append(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Understood. Continuing with the current task."}],
                }
            )
        else:
            result.append({"role": "user", "content": "Continuing."})

    result.extend(tail)
    return result
