import asyncio
import io
import unittest
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig


class _NoopTool:
    @property
    def name(self) -> str:
        return "noop"

    @property
    def description(self) -> str:
        return "noop"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        return "ok"


class _SessionManagerFake:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {
            "s1": {
                "id": "s1",
                "title": "Session One",
                "parent_session_id": None,
                "created_at": "2026-02-19T00:00:00+00:00",
                "updated_at": "2026-02-19T00:00:00+00:00",
                "status": "active",
            }
        }
        self._messages: dict[str, list[dict]] = {"s1": []}

    def load_messages(self, session_id: str) -> list[dict]:
        return list(self._messages.get(session_id, []))

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 20) -> list[dict]:
        return list(self._sessions.values())[:limit]

    def create_session(self, title: str | None = None, **_: Any) -> str:
        sid = "s-new"
        self._sessions[sid] = {
            "id": sid,
            "title": title or "Session New",
            "parent_session_id": None,
            "created_at": "2026-02-19T01:00:00+00:00",
            "updated_at": "2026-02-19T01:00:00+00:00",
            "status": "active",
        }
        self._messages[sid] = []
        return sid

    def set_session_title(self, session_id: str, title: str) -> None:
        self._sessions[session_id]["title"] = title

    def resolve_session_identifier(self, identifier: str) -> dict | None:
        identifier = identifier.strip()
        if identifier == "ambiguous":
            raise ValueError("ambiguous")
        if identifier in self._sessions:
            return self._sessions[identifier]
        for session in self._sessions.values():
            if session["title"].casefold() == identifier.casefold():
                return session
        return None

    def build_session_summary(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "title": self._sessions[session_id]["title"],
            "created_at": "2026-02-19T00:00:00+00:00",
            "updated_at": "2026-02-19T00:10:00+00:00",
            "message_count": 2,
            "user_message_count": 1,
            "assistant_message_count": 1,
            "checkpoint_count": 1,
            "last_user_preview": "hello",
            "last_assistant_preview": "world",
        }

    def fork_session(self, source_session_id: str) -> str:
        sid = "s-fork"
        self._sessions[sid] = {
            "id": sid,
            "title": "Fork Session",
            "parent_session_id": source_session_id,
            "created_at": "2026-02-19T02:00:00+00:00",
            "updated_at": "2026-02-19T02:00:00+00:00",
            "status": "active",
        }
        self._messages[sid] = []
        return sid

    def append_message(self, session_id: str, role: str, content: str | list[dict]) -> tuple[str, int]:
        msgs = self._messages.setdefault(session_id, [])
        msgs.append({"role": role, "content": content})
        return f"m{len(msgs)}", len(msgs)

    def record_tool_call(self, *args: Any, **kwargs: Any) -> str:
        return "tc1"


class _CheckpointManagerFake:
    enabled = True
    write_tools_only = True

    def __init__(self) -> None:
        self.created: list[str] = []
        self.rewinds: list[str] = []

    def create_checkpoint(self, session_id: str, user_message_id: str, scope: dict | None = None) -> str:
        cid = "cp1"
        self.created.append(cid)
        return cid

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        return []

    def list_checkpoints(self, session_id: str, limit: int = 20) -> list[dict]:
        return [
            {
                "id": "cp1",
                "created_at": "2026-02-19T00:05:00+00:00",
                "tools": ["write_file"],
                "user_preview": "update file",
            }
        ]

    def rewind_files(self, checkpoint_id: str) -> tuple[str, list[dict[str, str]]]:
        self.rewinds.append(checkpoint_id)
        return "s1", [{"path": "x.txt", "status": "restored", "detail": ""}]


class _EventsFake:
    def emit(self, *args: Any, **kwargs: Any) -> None:
        return


class AgentCommandTests(unittest.TestCase):
    def _make_agent(self) -> Agent:
        return Agent(
            AgentConfig(
                api_key="test",
                tools=[_NoopTool()],
                memory_enabled=True,
                session_id="s1",
                session_manager=_SessionManagerFake(),
                checkpoint_manager=_CheckpointManagerFake(),
                event_emitter=_EventsFake(),
            )
        )

    def test_help_includes_new_commands(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/help"))
        out = buf.getvalue()
        self.assertIn("/session new [title]", out)
        self.assertIn("/checkpoint list [limit]", out)

    def test_unknown_local_command_message(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/unknown"))
        self.assertIn("Unknown local command", buf.getvalue())

    def test_session_new_and_name(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session new Planning"))
            asyncio.run(agent._handle_session_command("/session name Planning Updated"))
        out = buf.getvalue()
        self.assertIn("Started new session:", out)
        self.assertIn("Session named: Planning Updated", out)

    def test_session_resume_by_name_prints_summary(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session resume Session One"))
        out = buf.getvalue()
        self.assertIn("Resumed session Session One", out)
        self.assertIn("Session summary:", out)

    def test_session_resume_not_found_and_ambiguous(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session resume missing"))
            asyncio.run(agent._handle_session_command("/session resume ambiguous"))
        out = buf.getvalue()
        self.assertIn("Session not found: missing", out)
        self.assertIn("ambiguous", out)

    def test_session_fork_updates_active(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session fork"))
        out = buf.getvalue()
        self.assertIn("Forked session s1 -> s-fork", out)

    def test_checkpoint_list_and_rewind_alias(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_checkpoint_command("/checkpoint list"))
            asyncio.run(agent._handle_checkpoint_command("/checkpoint rewind cp1"))
        out = buf.getvalue()
        self.assertIn("Recent checkpoints:", out)
        self.assertIn("Rewind cp1 results:", out)

    def test_checkpoint_usage_error_and_rewind_usage(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_checkpoint_command("/checkpoint list x"))
            asyncio.run(agent._handle_rewind_command("/rewind"))
        out = buf.getvalue()
        self.assertIn("Usage: /checkpoint list [limit]", out)
        self.assertIn("Usage: /rewind <checkpoint_id>", out)

    def test_run_handles_max_tokens_retry_then_stop(self) -> None:
        agent = self._make_agent()
        stream_result = (
            {"role": "assistant", "content": [{"type": "text", "text": "cut"}]},
            [],
            "max_tokens",
        )
        with patch.object(agent._provider, "stream_chat", side_effect=[stream_result] * 3):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run("hello"))
            out = buf.getvalue()
            self.assertIn("Stopped: response exceeded max_tokens", out)


if __name__ == "__main__":
    unittest.main()
