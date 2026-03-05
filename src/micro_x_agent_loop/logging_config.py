from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class LogConsumer(Protocol):
    def register(self, level: str) -> None: ...
    def describe(self, level: str) -> str: ...


class ConsoleLogConsumer:
    _instance: ClassVar[ConsoleLogConsumer | None] = None

    def __init__(self) -> None:
        self._handler_id: int | None = None
        self._level: str = "INFO"
        self._format = "<level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        ConsoleLogConsumer._instance = self

    def register(self, level: str) -> None:
        self._level = level
        self._handler_id = logger.add(
            sys.stderr,
            level=level,
            format=self._format,
        )

    def set_level(self, level: str) -> None:
        if self._handler_id is not None:
            logger.remove(self._handler_id)
            self._handler_id = None
        self._level = level
        if level != "OFF":
            self._handler_id = logger.add(
                sys.stderr,
                level=level,
                format=self._format,
            )

    @property
    def level(self) -> str:
        return self._level

    @classmethod
    def get_instance(cls) -> ConsoleLogConsumer | None:
        return cls._instance

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


class MetricsLogConsumer:
    def __init__(self, path: str = "metrics.jsonl"):
        self._path = path

    def register(self, level: str) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            self._path,
            level="INFO",
            filter=lambda record: record["extra"].get("metrics"),
            format="{message}",
            rotation="10 MB",
            retention=3,
        )

    def describe(self, level: str) -> str:
        return f"metrics ({self._path})"


class ApiPayloadLogConsumer:
    def __init__(self, path: str = "api_payloads.jsonl"):
        self._path = path

    def register(self, level: str) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            self._path,
            level="DEBUG",
            filter=lambda record: record["extra"].get("api_payload"),
            format="{message}",
            rotation="10 MB",
            retention=3,
        )

    def describe(self, level: str) -> str:
        return f"api_payload ({self._path})"


_CONSUMER_TYPES: dict[str, type] = {
    "console": ConsoleLogConsumer,
    "file": FileLogConsumer,
    "metrics": MetricsLogConsumer,
    "api_payload": ApiPayloadLogConsumer,
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
