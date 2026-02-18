import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class LogConsumer(Protocol):
    def register(self, level: str) -> None: ...
    def describe(self, level: str) -> str: ...


class ConsoleLogConsumer:
    def register(self, level: str) -> None:
        logger.add(
            sys.stderr,
            level=level,
            format="<level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        )

    def describe(self, level: str) -> str:
        return f"console (stderr, {level})"


class FileLogConsumer:
    def __init__(
        self,
        path: str = "agent.log",
        rotation: str = "10 MB",
        retention: int = 3,
    ):
        self._path = path
        self._rotation = rotation
        self._retention = retention

    def register(self, level: str) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            self._path,
            level=level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
            rotation=self._rotation,
            retention=self._retention,
        )

    def describe(self, level: str) -> str:
        return f"file ({self._path}, {level})"


_CONSUMER_TYPES: dict[str, type] = {
    "console": ConsoleLogConsumer,
    "file": FileLogConsumer,
}

_DEFAULT_CONSUMERS = [
    {"type": "console"},
    {"type": "file", "path": "agent.log"},
]


def setup_logging(
    level: str = "INFO",
    consumers: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Configure logging sinks. Returns a description of each registered consumer."""
    logger.remove()

    if consumers is None:
        consumers = _DEFAULT_CONSUMERS

    descriptions: list[str] = []

    for config in consumers:
        sink_type = config.get("type", "")
        cls = _CONSUMER_TYPES.get(sink_type)
        if cls is None:
            logger.warning(f"Unknown log consumer type: {sink_type!r}")
            continue

        # Separate known keys from consumer-specific kwargs
        kwargs = {k: v for k, v in config.items() if k not in ("type", "level")}
        sink_level = config.get("level", level)

        consumer = cls(**kwargs)
        consumer.register(sink_level)
        descriptions.append(consumer.describe(sink_level))

    return descriptions
