import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from micro_x_agent_loop.memory import EventEmitter, MemoryStore, SessionManager


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MemoryStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = PROJECT_ROOT / ".test-artifacts" / f"{self.__class__.__name__.lower()}-{uuid4().hex}"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        self._store = MemoryStore(str(self._tmp_dir / "memory.db"))
        self._events = EventEmitter(self._store)
        self._sessions = SessionManager(self._store, "test-model", self._events)

    def tearDown(self) -> None:
        self._store.close()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
