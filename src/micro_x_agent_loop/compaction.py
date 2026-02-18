import json
from typing import Protocol, runtime_checkable

import anthropic
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@runtime_checkable
class CompactionStrategy(Protocol):
    async def maybe_compact(self, messages: list[dict]) -> list[dict]: ...


class NoneCompactionStrategy:
    async def maybe_compact(self, messages: list[dict]) -> list[dict]:
        return messages


class SummarizeCompactionStrategy:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        threshold_tokens: int = 80_000,
        protected_tail_messages: int = 6,
    ):
        self._client = client
        self._model = model
        self._threshold_tokens = threshold_tokens
        self._protected_tail_messages = protected_tail_messages

    async def maybe_compact(self, messages: list[dict]) -> list[dict]:
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

        compactable = messages[compact_start:compact_end]

        logger.info(
            f"Compaction: estimated ~{estimated:,} tokens, threshold {self._threshold_tokens:,}"
            f" — compacting {len(compactable)} messages"
        )

        try:
            summary = await _summarize(self._client, self._model, compactable)
        except Exception as ex:
            logger.warning(f"Compaction failed: {ex}. Falling back to history trimming.")
            return messages

        result = _rebuild_messages(messages, compact_end, summary)

        summary_tokens = len(summary) // 4
        freed = estimated - estimate_tokens(result)
        logger.info(
            f"Compaction: summarized {len(compactable)} messages into ~{summary_tokens:,} tokens,"
            f" freed ~{freed:,} estimated tokens"
        )

        return result


def estimate_tokens(messages: list[dict]) -> int:
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    total_chars += len(block)
                elif isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        total_chars += len(block.get("text", ""))
                    elif block_type == "tool_use":
                        total_chars += len(block.get("name", ""))
                        total_chars += len(json.dumps(block.get("input", {})))
                    elif block_type == "tool_result":
                        result_content = block.get("content", "")
                        if isinstance(result_content, str):
                            total_chars += len(result_content)
                        elif isinstance(result_content, list):
                            for sub in result_content:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    total_chars += len(sub.get("text", ""))
    return total_chars // 4


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
    if len(text) <= 700:
        return text
    return text[:500] + "\n[...truncated...]\n" + text[-200:]


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

Format as a concise narrative summary.

---
CONVERSATION HISTORY:

"""


@retry(
    retry=retry_if_exception_type((
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    )),
    wait=wait_exponential(multiplier=10, min=10, max=320),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def _summarize(
    client: anthropic.AsyncAnthropic,
    model: str,
    messages: list[dict],
) -> str:
    formatted = _format_for_summarization(messages)

    # Cap summarization input
    if len(formatted) > 100_000:
        half = 50_000
        formatted = (
            formatted[:half]
            + "\n\n[...middle of conversation omitted for brevity...]\n\n"
            + formatted[-half:]
        )

    logger.debug(f"Compaction API request: model={model}, input_chars={len(formatted):,}")
    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0,
        messages=[{"role": "user", "content": _SUMMARIZE_PROMPT + formatted}],
    )

    usage = response.usage
    logger.debug(f"Compaction API response: input_tokens={usage.input_tokens}, output_tokens={usage.output_tokens}")

    return response.content[0].text


def _adjust_boundary(messages: list[dict], start: int, end: int) -> int:
    while end > start + 1:
        boundary_msg = messages[end - 1]
        if boundary_msg.get("role") != "assistant":
            break
        content = boundary_msg.get("content", [])
        if not isinstance(content, list):
            break
        has_tool_use = any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in content
        )
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
) -> list[dict]:
    first_msg = messages[0]
    original_content = first_msg.get("content", "")
    if isinstance(original_content, list):
        # Extract text from content blocks
        text_parts = [
            b.get("text", "") for b in original_content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        original_content = "\n".join(text_parts)

    merged_content = (
        original_content
        + "\n\n[CONTEXT SUMMARY]\n"
        + summary
        + "\n[END CONTEXT SUMMARY]"
    )
    merged_first = {"role": "user", "content": merged_content}

    tail = messages[compact_end:]

    result = [merged_first]

    # Insert assistant ack if needed for role alternation
    if tail and tail[0].get("role") == "user":
        result.append({
            "role": "assistant",
            "content": [{"type": "text", "text": "Understood. Continuing with the current task."}],
        })

    result.extend(tail)
    return result
