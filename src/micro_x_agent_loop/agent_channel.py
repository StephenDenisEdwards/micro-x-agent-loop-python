"""AgentChannel — bidirectional communication protocol between agent core and clients.

Each client type (CLI, WebSocket, broker subprocess) implements this protocol
to handle output events and human-in-the-loop interactions.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any, Protocol, runtime_checkable

import questionary
from questionary import Choice, Style



# ---------------------------------------------------------------------------
# ASK_USER_SCHEMA — tool definition for human-in-the-loop questioning
# ---------------------------------------------------------------------------

ASK_USER_SCHEMA: dict[str, Any] = {
    "name": "ask_user",
    "description": (
        "Ask the user a clarifying question. Use this when you need more information, "
        "want to present choices, or need approval before proceeding. "
        "The user's answer is returned as a tool result so you can continue."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            },
            "options": {
                "type": "array",
                "description": (
                    "Optional list of choices to present. Each option has a label "
                    "and description. The user can pick one or type a free-form answer."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Short label for this option.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Explanation of what this option means.",
                        },
                    },
                    "required": ["label", "description"],
                },
                "minItems": 2,
                "maxItems": 4,
            },
        },
        "required": ["question"],
    },
}


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentChannel(Protocol):
    """Bidirectional communication between agent core and any client."""

    # Agent → Client
    def emit_text_delta(self, text: str) -> None:
        """Called for each text token from the LLM stream."""
        ...

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        """Called when a tool begins execution."""
        ...

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        """Called when a tool finishes execution."""
        ...

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        """Called when a turn finishes, with usage/cost metrics."""
        ...

    def emit_error(self, message: str) -> None:
        """Called when an error occurs."""
        ...

    def emit_system_message(self, text: str) -> None:
        """Called for non-LLM system output (e.g. slash-command results)."""
        ...

    # Agent → Client → Agent (bidirectional)
    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        """Ask the user a question. Returns the answer text."""
        ...


# ---------------------------------------------------------------------------
# TerminalChannel — CLI implementation
# ---------------------------------------------------------------------------

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_ASK_USER_STYLE = Style([
    ("qmark", "fg:cyan bold"),
    ("question", "bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:cyan"),
    ("instruction", "fg:gray"),
])

_OTHER_SENTINEL = "__other__"


class TerminalChannel:
    """AgentChannel for the interactive CLI.

    Handles:
    - Text output with ``assistant> `` prefix
    - Spinner during tool execution (started/stopped by tool events)
    - Human-in-the-loop via terminal input (questionary)
    """

    def __init__(self, *, line_prefix: str = "assistant> ", user_prompt: str = "you> ") -> None:
        self._line_prefix = line_prefix
        self._user_prompt = user_prompt
        self._first_delta_in_turn = True
        self._spinner: _Spinner | None = None

    def emit_text_delta(self, text: str) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None
        if self._first_delta_in_turn:
            self._first_delta_in_turn = False
        print(text, end="", flush=True)

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        self._stop_spinner()
        self._spinner = _Spinner(prefix=self._line_prefix, label=f" Running {tool_name}...")
        self._spinner.start()

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        self._stop_spinner()

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        self._stop_spinner()
        self._first_delta_in_turn = True

    def emit_error(self, message: str) -> None:
        self._stop_spinner()
        print(f"\n{self._line_prefix}[Error: {message}]")

    def emit_system_message(self, text: str) -> None:
        self.print_line(text)

    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        self._stop_spinner()
        try:
            if options:
                answer = await asyncio.to_thread(self._prompt_with_options, question, options)
            else:
                answer = await asyncio.to_thread(self._prompt_free_text, question)
        except Exception:
            answer = await asyncio.to_thread(self._fallback_prompt, question, options or [])
        return answer

    def begin_streaming(self) -> None:
        """Called before an LLM stream starts. Starts the thinking spinner."""
        self._first_delta_in_turn = True
        self._spinner = _Spinner(prefix=self._line_prefix)
        self._spinner.start()

    def end_streaming(self) -> None:
        """Called after an LLM stream ends. Ensures spinner is stopped."""
        self._stop_spinner()

    def print_line(self, text: str) -> None:
        """Print a line through the spinner if active, or directly."""
        if self._spinner is not None:
            self._spinner.print_line(text)
        else:
            print(text, flush=True)

    # -- private helpers ---------------------------------------------------

    def _stop_spinner(self) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None

    @staticmethod
    def _prompt_with_options(question: str, options: list[dict[str, str]]) -> str:
        choices = [
            Choice(title=f"{opt['label']} \u2014 {opt.get('description', '')}", value=opt["label"])
            for opt in options
        ]
        choices.append(Choice(title="Other (type your own answer)", value=_OTHER_SENTINEL))
        selected = questionary.select(question, choices=choices, style=_ASK_USER_STYLE).ask()
        if selected is None:
            return ""
        if selected == _OTHER_SENTINEL:
            answer = questionary.text("Your answer:", style=_ASK_USER_STYLE).ask()
            return answer if answer is not None else ""
        return selected

    @staticmethod
    def _prompt_free_text(question: str) -> str:
        answer = questionary.text(question, style=_ASK_USER_STYLE).ask()
        return answer if answer is not None else ""

    def _fallback_prompt(self, question: str, options: list[dict[str, str]]) -> str:
        print(f"\n{self._line_prefix}Question: {question}")
        if options:
            for i, opt in enumerate(options, 1):
                print(f"{self._line_prefix}  {i}. {opt.get('label', '')} \u2014 {opt.get('description', '')}")
            print(f"{self._line_prefix}  (enter a number or type your own answer)")
        raw = input(self._user_prompt).strip()
        if options and raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]["label"]
        return raw


# ---------------------------------------------------------------------------
# BufferedChannel — for --run mode and tests
# ---------------------------------------------------------------------------


class BufferedChannel:
    """AgentChannel that accumulates text output into a buffer.

    Used by ``--run`` mode (autonomous) and tests. ``ask_user`` returns a
    default timeout message since there is no human to answer.
    """

    def __init__(self) -> None:
        self.text = ""
        self.tool_events: list[tuple[str, str, str]] = []  # (event, tool_use_id, tool_name)
        self.errors: list[str] = []
        self.turn_usages: list[dict[str, Any]] = []

    def emit_text_delta(self, text: str) -> None:
        self.text += text

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        self.tool_events.append(("started", tool_use_id, tool_name))

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        self.tool_events.append(("completed", tool_use_id, tool_name))

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        self.turn_usages.append(usage)

    def emit_error(self, message: str) -> None:
        self.errors.append(message)

    def emit_system_message(self, text: str) -> None:
        self.text += text + "\n"

    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        return (
            "No response from human — question timed out. "
            "Proceed with your best judgement or report that you cannot continue."
        )


# ---------------------------------------------------------------------------
# BrokerChannel — for broker subprocess runs with HITL
# ---------------------------------------------------------------------------


class BrokerChannel:
    """AgentChannel for broker subprocess runs with async human-in-the-loop.

    Output events are no-ops (subprocess stdout is captured by the runner).
    ``ask_user`` posts questions to the broker HTTP API and polls for answers.
    """

    def __init__(self, broker_url: str, run_id: str, *, timeout: int = 300, poll_interval: int = 3) -> None:
        self._broker_url = broker_url.rstrip("/")
        self._run_id = run_id
        self._timeout = timeout
        self._poll_interval = poll_interval

    def emit_text_delta(self, text: str) -> None:
        pass

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        pass

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        pass

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        pass

    def emit_error(self, message: str) -> None:
        pass

    def emit_system_message(self, text: str) -> None:
        pass

    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        from loguru import logger
        import httpx

        payload: dict[str, Any] = {"question": question}
        if options:
            payload["options"] = options

        async with httpx.AsyncClient(timeout=10) as client:
            url = f"{self._broker_url}/api/runs/{self._run_id}/questions"
            try:
                resp = await client.post(url, json=payload)
                if not resp.is_success:
                    logger.warning(f"Failed to post HITL question: HTTP {resp.status_code}")
                    return _NO_RESPONSE_MSG
                data = resp.json()
                question_id = data["question_id"]
            except Exception as ex:
                logger.warning(f"Failed to reach broker for HITL question: {ex}")
                return _NO_RESPONSE_MSG

            logger.info(f"HITL question posted: id={question_id}, timeout={self._timeout}s")

            poll_url = f"{self._broker_url}/api/runs/{self._run_id}/questions/{question_id}"
            elapsed = 0
            while elapsed < self._timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval
                try:
                    resp = await client.get(poll_url)
                    if not resp.is_success:
                        continue
                    data = resp.json()
                    if data["status"] == "answered":
                        logger.info(f"HITL answer received for question {question_id}")
                        return data["answer"]
                    if data["status"] == "timed_out":
                        logger.info(f"HITL question {question_id} timed out")
                        break
                except Exception:
                    continue

        return _NO_RESPONSE_MSG


_NO_RESPONSE_MSG = (
    "No response from human — question timed out. "
    "Proceed with your best judgement or report that you cannot continue."
)


# ---------------------------------------------------------------------------
# _Spinner — terminal spinner (private implementation detail)
# ---------------------------------------------------------------------------


class _Spinner:
    """Thread-based spinner that renders on the current line using \\r."""

    def __init__(self, prefix: str = "", label: str = " Thinking...") -> None:
        self._prefix = prefix
        self._label = label
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_width = 1 + len(label)
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        clear = self._prefix + " " * self._frame_width
        sys.stdout.write("\r" + clear + "\r" + self._prefix)
        sys.stdout.flush()

    def print_line(self, text: str) -> None:
        with self._lock:
            sys.stdout.write(f"\r\033[K{text}\n")
            if not self._stop_event.is_set():
                frame = _SPINNER_FRAMES[0] + self._label
                sys.stdout.write(self._prefix + frame)
            sys.stdout.flush()

    def _run(self) -> None:
        i = 0
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)] + self._label
                    sys.stdout.write("\r" + self._prefix + frame)
                    sys.stdout.flush()
                self._stop_event.wait(0.08)
                i += 1
        except (UnicodeEncodeError, OSError):
            pass
