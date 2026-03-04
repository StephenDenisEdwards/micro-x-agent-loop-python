"""Pseudo-tool that lets the LLM pause and ask the user a clarifying question."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import questionary
from questionary import Choice, Style

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

_OTHER_SENTINEL = "__other__"

_ASK_USER_STYLE = Style([
    ("qmark", "fg:cyan bold"),
    ("question", "bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:cyan"),
    ("instruction", "fg:gray"),
])


class AskUserHandler:
    """Handles ``ask_user`` pseudo-tool calls by prompting the user in the terminal."""

    def __init__(self, *, line_prefix: str, user_prompt: str) -> None:
        self._line_prefix = line_prefix
        self._user_prompt = user_prompt

    @staticmethod
    def is_ask_user_call(tool_name: str) -> bool:
        return tool_name == "ask_user"

    @staticmethod
    def get_schema() -> dict[str, Any]:
        return ASK_USER_SCHEMA

    # -- sync helpers (run inside asyncio.to_thread) -----------------------

    @staticmethod
    def _prompt_with_options(question: str, options: list[dict[str, str]]) -> str:
        """Interactive arrow-key selection with an appended 'Other' free-text option."""
        choices = [
            Choice(title=f"{opt['label']} \u2014 {opt.get('description', '')}", value=opt["label"])
            for opt in options
        ]
        choices.append(Choice(title="Other (type your own answer)", value=_OTHER_SENTINEL))

        selected = questionary.select(
            question,
            choices=choices,
            style=_ASK_USER_STYLE,
        ).ask()

        if selected is None:
            # User pressed Ctrl-C or prompt was aborted
            return ""

        if selected == _OTHER_SENTINEL:
            answer = questionary.text("Your answer:", style=_ASK_USER_STYLE).ask()
            return answer if answer is not None else ""

        return selected

    @staticmethod
    def _prompt_free_text(question: str) -> str:
        """Simple styled text input when no options are provided."""
        answer = questionary.text(question, style=_ASK_USER_STYLE).ask()
        return answer if answer is not None else ""

    # -- fallback (non-interactive terminal) -------------------------------

    def _fallback_prompt(self, question: str, options: list[dict[str, str]]) -> str:
        """Plain print/input fallback for piped stdin or non-interactive terminals."""
        print(f"\n{self._line_prefix}Question: {question}")
        if options:
            for i, opt in enumerate(options, 1):
                label = opt.get("label", "")
                desc = opt.get("description", "")
                print(f"{self._line_prefix}  {i}. {label} \u2014 {desc}")
            print(f"{self._line_prefix}  (enter a number or type your own answer)")

        raw = input(self._user_prompt).strip()

        if options and raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]["label"]
        return raw

    # -- main entry point --------------------------------------------------

    async def handle(self, tool_input: dict[str, Any]) -> str:
        question = tool_input.get("question", "")
        options: list[dict[str, str]] = tool_input.get("options") or []

        try:
            if options:
                answer = await asyncio.to_thread(self._prompt_with_options, question, options)
            else:
                answer = await asyncio.to_thread(self._prompt_free_text, question)
        except Exception:
            # Non-interactive terminal, piped stdin, or questionary failure
            answer = await asyncio.to_thread(self._fallback_prompt, question, options)

        return json.dumps({"answer": answer})
