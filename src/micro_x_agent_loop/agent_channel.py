"""AgentChannel — bidirectional communication protocol between agent core and clients.

Each client type (CLI, WebSocket, broker subprocess) implements this protocol
to handle output events and human-in-the-loop interactions.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from rich.console import Console

from micro_x_agent_loop.terminal_prompter import fallback_prompt, prompt_free_text, prompt_with_options
from micro_x_agent_loop.terminal_renderer import PlainSpinner, RichRenderer

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


class TerminalChannel:
    """AgentChannel for the interactive CLI.

    Handles:
    - Text output with optional markdown rendering (``rich.Live`` + ``rich.Markdown``)
    - Spinner during tool execution (``rich.spinner`` or thread-based fallback)
    - Human-in-the-loop via terminal input (questionary)

    When ``markdown=True`` (default), uses the buffer-and-rerender pattern:
    tokens accumulate in a buffer and are re-rendered as markdown on each delta.
    When ``markdown=False``, falls back to plain ``print()`` output.
    """

    def __init__(
        self,
        *,
        line_prefix: str = "assistant> ",
        user_prompt: str = "you> ",
        markdown: bool = True,
    ) -> None:
        self._line_prefix = line_prefix
        self._user_prompt = user_prompt
        self._markdown = markdown
        self._first_delta_in_turn = True
        # Plain-text mode state
        self._spinner: PlainSpinner | None = None
        # Markdown mode state
        self._renderer: RichRenderer | None = None

    def emit_text_delta(self, text: str) -> None:
        if self._markdown:
            self._ensure_renderer()
            assert self._renderer is not None
            self._renderer.append_text(text)
        else:
            if self._spinner is not None:
                self._spinner.stop()
                self._spinner = None
            if self._first_delta_in_turn:
                self._first_delta_in_turn = False
            print(text, end="", flush=True)

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        if self._markdown:
            self._ensure_renderer()
            assert self._renderer is not None
            self._renderer.finalize_text()
            self._renderer.start_spinner(f" Running {tool_name}...")
        else:
            self._stop_spinner()
            self._spinner = PlainSpinner(prefix=self._line_prefix, label=f" Running {tool_name}...")
            self._spinner.start()

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        if self._markdown:
            if self._renderer is not None:
                self._renderer.stop_spinner()
        else:
            self._stop_spinner()

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        if self._markdown:
            if self._renderer is not None:
                self._renderer.finalize_text()
                self._renderer.stop()
                self._renderer = None
        else:
            self._stop_spinner()
        self._first_delta_in_turn = True

    def emit_error(self, message: str) -> None:
        if self._markdown:
            if self._renderer is not None:
                self._renderer.stop()
                self._renderer = None
            console = Console()
            console.print(f"\n{self._line_prefix}[Error: {message}]", style="bold red")
        else:
            self._stop_spinner()
            print(f"\n{self._line_prefix}[Error: {message}]")

    def emit_system_message(self, text: str) -> None:
        self.print_line(text)

    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        if self._markdown:
            if self._renderer is not None:
                self._renderer.finalize_text()
                self._renderer.stop()
                self._renderer = None
        else:
            self._stop_spinner()
        try:
            if options:
                answer = await asyncio.to_thread(prompt_with_options, question, options)
            else:
                answer = await asyncio.to_thread(prompt_free_text, question)
        except Exception:
            answer = await asyncio.to_thread(
                fallback_prompt, question, options or [],
                line_prefix=self._line_prefix, user_prompt=self._user_prompt,
            )
        return answer

    def begin_streaming(self) -> None:
        """Called before an LLM stream starts. Starts the thinking spinner."""
        self._first_delta_in_turn = True
        if self._markdown:
            self._renderer = RichRenderer(self._line_prefix)
            self._renderer.start_spinner()
        else:
            self._spinner = PlainSpinner(prefix=self._line_prefix)
            self._spinner.start()

    def end_streaming(self) -> None:
        """Called after an LLM stream ends. Ensures renderer/spinner is stopped."""
        if self._markdown:
            if self._renderer is not None:
                self._renderer.finalize_text()
                self._renderer.stop()
                self._renderer = None
        else:
            self._stop_spinner()

    def print_line(self, text: str) -> None:
        """Print a line through the renderer/spinner if active, or directly."""
        if self._markdown and self._renderer is not None:
            self._renderer.print_line(text)
        elif self._spinner is not None:
            self._spinner.print_line(text)
        else:
            print(text, flush=True)

    # -- private helpers ---------------------------------------------------

    def _ensure_renderer(self) -> None:
        """Ensure a RichRenderer exists, creating one if needed."""
        if self._renderer is None:
            self._renderer = RichRenderer(self._line_prefix)
        if self._renderer.is_showing_spinner():
            self._renderer.switch_to_markdown()

    def _stop_spinner(self) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None


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
        import httpx
        from loguru import logger

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
                        return str(data["answer"])
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
