from __future__ import annotations

from collections.abc import Callable

from tenacity import retry_if_exception, retry_if_exception_type, stop_after_attempt, wait_exponential

from micro_x_agent_loop.llm_client import _on_retry


def default_retry_kwargs(exception_types: tuple[type[Exception], ...]) -> dict:
    return {
        "retry": retry_if_exception_type(exception_types),
        "wait": wait_exponential(multiplier=10, min=10, max=320),
        "stop": stop_after_attempt(5),
        "before_sleep": _on_retry,
        "reraise": True,
    }


def predicate_retry_kwargs(predicate: Callable[[BaseException], bool]) -> dict:
    """Retry config gated by a predicate rather than exception type.

    Used where retryability depends on more than the exception class — e.g.
    Gemini surfaces 429 (rate limit), 400 (bad request) and 404 (not found) all
    as ``ClientError``, so only ``code == 429`` should retry. Same backoff and
    attempt budget as ``default_retry_kwargs``.
    """
    return {
        "retry": retry_if_exception(predicate),
        "wait": wait_exponential(multiplier=10, min=10, max=320),
        "stop": stop_after_attempt(5),
        "before_sleep": _on_retry,
        "reraise": True,
    }
