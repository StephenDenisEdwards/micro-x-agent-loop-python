from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from micro_x_agent_loop.llm_client import Spinner, _on_retry


def default_retry_kwargs(exception_types: tuple[type[Exception], ...]) -> dict:
    return {
        "retry": retry_if_exception_type(exception_types),
        "wait": wait_exponential(multiplier=10, min=10, max=320),
        "stop": stop_after_attempt(5),
        "before_sleep": _on_retry,
        "reraise": True,
    }


@contextmanager
def streaming_spinner(*, prefix: str = "", label: str = " Thinking...") -> Iterator[Spinner]:
    spinner = Spinner(prefix=prefix, label=label)
    spinner.start()
    try:
        yield spinner
    finally:
        spinner.stop()
