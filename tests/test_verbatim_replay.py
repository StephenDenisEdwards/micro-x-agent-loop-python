"""Verbatim replay — exact per-call request capture + /replay --full expansion."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.observability import ObservabilityEmitter
from micro_x_agent_loop.redaction import RegexRedactor
from micro_x_agent_loop.session_replay import reconstruct_session


class _F:
    def __init__(self, emitter: EventEmitter, sid: str) -> None:
        self._emitter, self._sid = emitter, sid

    def emit_event(self, event_type: str, payload: dict) -> None:
        self._emitter.emit(self._sid, event_type, payload)


class VerbatimCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "m.db"))
        self.emitter = EventEmitter(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def _sm(self, *, capture: bool, redact: bool = False) -> SessionManager:
        return SessionManager(
            self.store, "m", self.emitter,
            redactor=RegexRedactor() if redact else None,
            verbatim_capture=capture,
        )

    def test_disabled_returns_none_and_persists_nothing(self) -> None:
        sm = self._sm(capture=False)
        sid = sm.create_session("t")
        rid = sm.persist_llm_request(
            sid, turn_number=1, iteration=0, system_prompt_sha256="abc",
            messages=[{"role": "user", "content": "hi"}], tools=[{"name": "echo"}],
        )
        self.assertIsNone(rid)
        self.assertEqual(list(self.store.execute("SELECT * FROM llm_requests")), [])

    def test_capture_persists_exact_messages_and_tools(self) -> None:
        sm = self._sm(capture=True)
        sid = sm.create_session("t")
        messages = [{"role": "user", "content": "build X"}, {"role": "assistant", "content": "ok"}]
        tools = [{"name": "echo", "input_schema": {"type": "object"}}]
        rid = sm.persist_llm_request(
            sid, turn_number=2, iteration=1, system_prompt_sha256="deadbeef", messages=messages, tools=tools,
        )
        self.assertIsNotNone(rid)
        row = next(iter(self.store.execute("SELECT messages_json, tools_sha256, turn_number FROM llm_requests")))
        self.assertEqual(json.loads(row["messages_json"]), messages)  # exact, verbatim
        self.assertEqual(row["turn_number"], 2)
        tools_row = next(
            iter(self.store.execute("SELECT json FROM tool_schemas WHERE sha256 = ?", (row["tools_sha256"],)))
        )
        self.assertEqual(json.loads(tools_row["json"]), tools)  # exact tool schemas

    def test_redaction_applies_to_verbatim_copy(self) -> None:
        sm = self._sm(capture=True, redact=True)
        sid = sm.create_session("t")
        sm.persist_llm_request(
            sid, turn_number=1, iteration=0, system_prompt_sha256="x",
            messages=[{"role": "user", "content": "my api_key=supersecretvalue here"}],
            tools=[],
        )
        row = next(iter(self.store.execute("SELECT messages_json FROM llm_requests")))
        self.assertIn("[REDACTED]", row["messages_json"])
        self.assertNotIn("supersecretvalue", row["messages_json"])


class FullReplayRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "m.db"))
        self.emitter = EventEmitter(self.store)
        self.sm = SessionManager(self.store, "m", self.emitter, verbatim_capture=True)
        self.sid = self.sm.create_session("t")
        self.obs = ObservabilityEmitter(_F(self.emitter, self.sid))

    def tearDown(self) -> None:
        self.store.close()

    def _seed_llm_call(self) -> None:
        sha = self.sm.persist_system_prompt("YOU ARE A HELPFUL AGENT")
        rid = self.sm.persist_llm_request(
            self.sid, turn_number=1, iteration=0, system_prompt_sha256=sha,
            messages=[{"role": "user", "content": "exact user message"}],
            tools=[{"name": "web_fetch"}],
        )
        self.obs.emit(
            "llm.call",
            {
                "session_id": self.sid, "turn_number": 1, "call_type": "main",
                "effective_provider": "anthropic", "effective_model": "claude",
                "system_prompt_sha256": sha, "system_prompt_chars": 23,
                "tool_names": ["web_fetch"], "request_id": rid,
            },
            turn_number=1, iteration=0,
        )

    def test_full_expands_verbatim_request(self) -> None:
        self._seed_llm_call()
        text = "\n".join(reconstruct_session(self.store, self.sid, full=True))
        self.assertIn("verbatim request", text)
        self.assertIn("YOU ARE A HELPFUL AGENT", text)        # full system prompt
        self.assertIn("exact user message", text)             # full messages
        self.assertIn("web_fetch", text)                      # full tool schema

    def test_non_full_keeps_hash_only(self) -> None:
        self._seed_llm_call()
        text = "\n".join(reconstruct_session(self.store, self.sid, full=False))
        self.assertNotIn("YOU ARE A HELPFUL AGENT", text)
        self.assertIn("prompt=sha:", text)

    def test_full_without_capture_notes_missing(self) -> None:
        sha = self.sm.persist_system_prompt("SOME PROMPT")
        self.obs.emit(
            "llm.call",
            {"session_id": self.sid, "turn_number": 1, "call_type": "main",
             "system_prompt_sha256": sha, "tool_names": [], "request_id": None},
            turn_number=1, iteration=0,
        )
        text = "\n".join(reconstruct_session(self.store, self.sid, full=True))
        self.assertIn("SOME PROMPT", text)  # prompt always available
        self.assertIn("not captured", text)  # messages/tools note


if __name__ == "__main__":
    unittest.main()
