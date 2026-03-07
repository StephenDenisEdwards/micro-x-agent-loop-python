from __future__ import annotations

from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from micro_x_agent_loop.llm_client import _on_retry


def default_retry_kwargs(exception_types: tuple[type[Exception], ...]) -> dict:
    return {
        "retry": retry_if_exception_type(exception_types),
        "wait": wait_exponential(multiplier=10, min=10, max=320),
        "stop": stop_after_attempt(5),
        "before_sleep": _on_retry,
        "reraise": True,
    }
