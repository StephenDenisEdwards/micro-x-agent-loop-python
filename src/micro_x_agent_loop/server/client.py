"""WebSocket CLI client — connects to a running API server."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
from loguru import logger

from micro_x_agent_loop.agent_channel import TerminalChannel


async def run_client(
    server_url: str,
    *,
    session_id: str | None = None,
    api_secret: str | None = None,
) -> None:
    """Connect the CLI to a running API server via WebSocket.

    Provides the same interactive experience as the direct REPL:
    spinner during tool calls, ``assistant>`` prefix, and terminal-based
    ``ask_user`` prompts.
    """
    base_url = server_url.rstrip("/")
    ws_scheme = "wss" if base_url.startswith("https") else "ws"
    ws_base = base_url.replace("https://", ws_scheme + "://").replace("http://", ws_scheme + "://")

    headers: dict[str, str] = {}
    if api_secret:
        headers["Authorization"] = f"Bearer {api_secret}"

    # Health check
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{base_url}/api/health", headers=headers)
            if resp.status_code != 200:
                print(f"Server health check failed: {resp.status_code}")
                return
            health = resp.json()
    except httpx.ConnectError:
        print(f"Cannot connect to server at {base_url}")
        return

    # Create or reuse session
    if not session_id:
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.post(f"{base_url}/api/sessions", headers=headers)
                if resp.status_code == 200:
                    session_id = resp.json().get("session_id")
        except Exception:
            pass
        if not session_id:
            session_id = str(uuid.uuid4())

    print(
        f"Connected to {base_url} "
        f"(tools={health.get('tools', '?')}, "
        f"memory={'on' if health.get('memory_enabled') else 'off'})"
    )
    print(f"Session: {session_id}")
    print("Type 'exit' to quit.\n")

    ws_url = f"{ws_base}/api/ws/{session_id}"

    try:
        import websockets
    except ImportError:
        print("Error: 'websockets' package required for client mode.")
        print("Install with: pip install websockets")
        return

    channel = TerminalChannel()
    extra_headers = [(k, v) for k, v in headers.items()] if headers else None

    try:
        async with websockets.connect(ws_url, additional_headers=extra_headers) as ws:
            # Start receiver task
            receiver_done = asyncio.Event()
            turn_complete = asyncio.Event()
            turn_complete.set()  # Initially ready for input

            async def receiver() -> None:
                try:
                    async for raw_msg in ws:
                        data = json.loads(raw_msg)
                        msg_type = data.get("type", "")

                        if msg_type == "text_delta":
                            channel.emit_text_delta(data.get("text", ""))

                        elif msg_type == "tool_started":
                            channel.emit_tool_started(
                                data.get("tool_use_id", ""),
                                data.get("tool", ""),
                            )

                        elif msg_type == "tool_completed":
                            channel.emit_tool_completed(
                                data.get("tool_use_id", ""),
                                data.get("tool", ""),
                                data.get("error", False),
                            )

                        elif msg_type == "turn_complete":
                            channel.emit_turn_complete(data.get("usage", {}))
                            print()  # newline after response
                            turn_complete.set()

                        elif msg_type == "system_message":
                            channel.print_line(data.get("text", ""))

                        elif msg_type == "error":
                            channel.emit_error(data.get("message", "Unknown error"))
                            turn_complete.set()

                        elif msg_type == "question":
                            # Handle ask_user via terminal
                            question_id = data.get("id", "")
                            question_text = data.get("text", "")
                            options = data.get("options")
                            answer = await channel.ask_user(question_text, options)
                            await ws.send(json.dumps({
                                "type": "answer",
                                "question_id": question_id,
                                "text": answer,
                            }))

                        elif msg_type == "pong":
                            pass

                except websockets.ConnectionClosed:
                    pass
                finally:
                    receiver_done.set()
                    turn_complete.set()

            recv_task = asyncio.create_task(receiver())
            from prompt_toolkit import PromptSession
            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

            bindings = KeyBindings()

            @bindings.add("enter")
            def _submit(event: KeyPressEvent) -> None:
                event.current_buffer.validate_and_handle()

            @bindings.add("s-enter")
            @bindings.add("escape", "enter")
            def _newline(event: KeyPressEvent) -> None:
                event.current_buffer.insert_text("\n")

            session: PromptSession[str] = PromptSession(
                message=HTML("<b>you&gt; </b>"),
                multiline=True,
                key_bindings=bindings,
                prompt_continuation=".... ",
            )

            try:
                while not receiver_done.is_set():
                    # Wait for turn to complete before prompting
                    await turn_complete.wait()
                    if receiver_done.is_set():
                        break

                    try:
                        user_input = await asyncio.to_thread(session.prompt)
                    except (EOFError, KeyboardInterrupt):
                        break

                    trimmed = user_input.strip()
                    if trimmed in ("exit", "quit"):
                        break
                    if not trimmed:
                        continue

                    turn_complete.clear()
                    channel.begin_streaming()
                    await ws.send(json.dumps({"type": "message", "text": trimmed}))
            finally:
                recv_task.cancel()
                try:
                    await recv_task
                except asyncio.CancelledError:
                    pass

    except websockets.InvalidStatusCode as ex:
        if ex.status_code == 401:
            print("Authentication failed. Set SERVER_API_SECRET or use --server start with matching secret.")
        else:
            print(f"WebSocket connection failed: {ex}")
    except Exception as ex:
        print(f"Connection error: {ex}")
