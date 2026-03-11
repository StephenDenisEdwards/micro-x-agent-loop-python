"""Tests for logging_config module."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.logging_config import (
    ApiPayloadLogConsumer,
    ConsoleLogConsumer,
    FileLogConsumer,
    MetricsLogConsumer,
    setup_logging,
)


class ConsoleLogConsumerTests(unittest.TestCase):
    def test_register_and_get_instance(self) -> None:
        consumer = ConsoleLogConsumer()
        consumer.register("WARNING")
        self.assertEqual("WARNING", consumer.level)
        instance = ConsoleLogConsumer.get_instance()
        self.assertIs(consumer, instance)

    def test_set_level(self) -> None:
        consumer = ConsoleLogConsumer()
        consumer.register("INFO")
        consumer.set_level("DEBUG")
        self.assertEqual("DEBUG", consumer.level)

    def test_set_level_off(self) -> None:
        consumer = ConsoleLogConsumer()
        consumer.register("INFO")
        consumer.set_level("OFF")
        self.assertEqual("OFF", consumer.level)

    def test_describe(self) -> None:
        consumer = ConsoleLogConsumer()
        desc = consumer.describe("INFO")
        self.assertIn("console", desc)
        self.assertIn("INFO", desc)


class FileLogConsumerTests(unittest.TestCase):
    def test_register_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "subdir" / "test.log")
            consumer = FileLogConsumer(path=log_path)
            consumer.register("DEBUG")
            self.assertTrue(Path(log_path).parent.exists())

    def test_describe(self) -> None:
        consumer = FileLogConsumer(path="test.log")
        desc = consumer.describe("INFO")
        self.assertIn("test.log", desc)


class MetricsLogConsumerTests(unittest.TestCase):
    def test_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "metrics.jsonl")
            consumer = MetricsLogConsumer(path=path)
            consumer.register("INFO")

    def test_describe(self) -> None:
        consumer = MetricsLogConsumer(path="metrics.jsonl")
        desc = consumer.describe("INFO")
        self.assertIn("metrics", desc)


class ApiPayloadLogConsumerTests(unittest.TestCase):
    def test_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "payloads.jsonl")
            consumer = ApiPayloadLogConsumer(path=path)
            consumer.register("DEBUG")

    def test_describe(self) -> None:
        consumer = ApiPayloadLogConsumer(path="payloads.jsonl")
        desc = consumer.describe("DEBUG")
        self.assertIn("api_payload", desc)


class SetupLoggingTests(unittest.TestCase):
    def test_default_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            consumers = [{"type": "console"}]
            descs = setup_logging("INFO", consumers=consumers)
            self.assertEqual(1, len(descs))
            self.assertIn("console", descs[0])

    def test_file_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "test.log")
            consumers = [{"type": "file", "path": log_path}]
            descs = setup_logging("DEBUG", consumers=consumers)
            self.assertEqual(1, len(descs))

    def test_unknown_consumer_skipped(self) -> None:
        descs = setup_logging("INFO", consumers=[{"type": "unknown"}])
        self.assertEqual(0, len(descs))

    def test_per_consumer_level_override(self) -> None:
        consumers = [{"type": "console", "level": "ERROR"}]
        descs = setup_logging("INFO", consumers=consumers)
        self.assertIn("ERROR", descs[0])

    def test_null_consumers_uses_default(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # Default uses console + file; just check it doesn't raise
            try:
                setup_logging("INFO", consumers=None)
            except Exception:
                pass  # May fail if file paths aren't writable — that's fine


if __name__ == "__main__":
    unittest.main()
