"""Tests for BrokerService lifecycle helpers."""

from __future__ import annotations

import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from micro_x_agent_loop.broker.service import BrokerService


class BrokerServicePidTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pid_path(self, name: str = "broker.pid") -> str:
        return str(Path(self._tmp.name) / name)

    def test_try_acquire_pid_creates_file(self) -> None:
        pid_path = self._pid_path()
        svc = BrokerService(pid_path=pid_path)
        result = svc._try_acquire_pid()
        self.assertTrue(result)
        self.assertTrue(Path(pid_path).exists())

    def test_try_acquire_pid_returns_false_when_running(self) -> None:
        pid_path = self._pid_path()
        # Write our own PID (which exists)
        Path(pid_path).parent.mkdir(parents=True, exist_ok=True)
        Path(pid_path).write_text(str(os.getpid()))
        svc = BrokerService(pid_path=pid_path)
        result = svc._try_acquire_pid()
        self.assertFalse(result)

    def test_try_acquire_pid_removes_stale(self) -> None:
        pid_path = self._pid_path()
        Path(pid_path).parent.mkdir(parents=True, exist_ok=True)
        # Write a PID that does not exist
        Path(pid_path).write_text("99999999")
        svc = BrokerService(pid_path=pid_path)
        result = svc._try_acquire_pid()
        self.assertTrue(result)

    def test_try_acquire_pid_invalid_content(self) -> None:
        pid_path = self._pid_path()
        Path(pid_path).parent.mkdir(parents=True, exist_ok=True)
        # Non-integer content → stale, should remove and re-acquire
        Path(pid_path).write_text("notanint")
        svc = BrokerService(pid_path=pid_path)
        result = svc._try_acquire_pid()
        self.assertTrue(result)

    def test_remove_pid(self) -> None:
        pid_path = self._pid_path()
        svc = BrokerService(pid_path=pid_path)
        svc._try_acquire_pid()
        self.assertTrue(Path(pid_path).exists())
        svc._remove_pid()
        self.assertFalse(Path(pid_path).exists())

    def test_remove_pid_no_file(self) -> None:
        pid_path = self._pid_path()
        svc = BrokerService(pid_path=pid_path)
        svc._remove_pid()  # Should not raise

    def test_cleanup(self) -> None:
        pid_path = self._pid_path()
        svc = BrokerService(pid_path=pid_path, db_path=str(Path(self._tmp.name) / "b.db"))
        svc._try_acquire_pid()
        # _cleanup removes PID and closes store (store is None here)
        svc._cleanup()
        self.assertFalse(Path(pid_path).exists())


class BrokerServiceReadPidTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pid_path(self) -> str:
        return str(Path(self._tmp.name) / "broker.pid")

    def test_read_pid_no_file(self) -> None:
        pid_path = self._pid_path()
        result = BrokerService.read_pid(pid_path)
        self.assertIsNone(result)

    def test_read_pid_running_process(self) -> None:
        pid_path = self._pid_path()
        my_pid = os.getpid()
        Path(pid_path).write_text(str(my_pid))
        result = BrokerService.read_pid(pid_path)
        self.assertEqual(my_pid, result)

    def test_read_pid_dead_process(self) -> None:
        pid_path = self._pid_path()
        Path(pid_path).write_text("99999999")
        result = BrokerService.read_pid(pid_path)
        self.assertIsNone(result)

    def test_read_pid_invalid_content(self) -> None:
        pid_path = self._pid_path()
        Path(pid_path).write_text("notapid")
        result = BrokerService.read_pid(pid_path)
        self.assertIsNone(result)


class BrokerServiceStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pid_path(self) -> str:
        return str(Path(self._tmp.name) / "broker.pid")

    def test_stop_broker_no_file(self) -> None:
        pid_path = self._pid_path()
        result = BrokerService.stop_broker(pid_path)
        self.assertFalse(result)

    def test_stop_broker_sends_sigterm(self) -> None:
        pid_path = self._pid_path()
        my_pid = os.getpid()
        Path(pid_path).write_text(str(my_pid))
        with patch("os.kill") as mock_kill:
            result = BrokerService.stop_broker(pid_path)
            self.assertTrue(result)
            mock_kill.assert_called_with(my_pid, signal.SIGTERM)
        # PID file should be removed after stop
        self.assertFalse(Path(pid_path).exists())

    def test_stop_broker_dead_process(self) -> None:
        pid_path = self._pid_path()
        Path(pid_path).write_text("99999999")
        result = BrokerService.stop_broker(pid_path)
        # Dead process → should return False and remove stale PID file
        self.assertFalse(result)
        self.assertFalse(Path(pid_path).exists())


class BrokerServiceHandleShutdownTests(unittest.TestCase):
    def test_handle_shutdown_with_scheduler_and_ingresses(self) -> None:
        svc = BrokerService()
        scheduler = MagicMock()
        ingress1 = MagicMock()
        ingress2 = MagicMock()
        svc._scheduler = scheduler
        svc._polling_ingresses = [ingress1, ingress2]

        svc._handle_shutdown()

        scheduler.stop.assert_called_once()
        ingress1.stop.assert_called_once()
        ingress2.stop.assert_called_once()

    def test_handle_shutdown_no_scheduler(self) -> None:
        svc = BrokerService()
        # Should not raise even with no scheduler
        svc._handle_shutdown()


if __name__ == "__main__":
    unittest.main()
