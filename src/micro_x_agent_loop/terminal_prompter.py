"""Terminal interactive prompts — questionary-based user input.

Extracted from ``agent_channel.py`` to give prompting its own module.
"""

from __future__ import annotations

import questionary
from questionary import Choice, Style

_ASK_USER_STYLE = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:cyan"),
        ("instruction", "fg:gray"),
    ]
)

_OTHER_SENTINEL = "__other__"


def prompt_with_options(question: str, options: list[dict[str, str]]) -> str:
    """Present a selection list with an 'Other' escape hatch."""
    choices = [
        Choice(title=f"{opt['label']} \u2014 {opt.get('description', '')}", value=opt["label"]) for opt in options
    ]
    choices.append(Choice(title="Other (type your own answer)", value=_OTHER_SENTINEL))
    selected = questionary.select(question, choices=choices, style=_ASK_USER_STYLE).ask()
    if selected is None:
        return ""
    if selected == _OTHER_SENTINEL:
        answer = questionary.text("Your answer:", style=_ASK_USER_STYLE).ask()
        return str(answer) if answer is not None else ""
    return str(selected)


def prompt_free_text(question: str) -> str:
    """Prompt for free-form text input."""
    answer = questionary.text(question, style=_ASK_USER_STYLE).ask()
    return answer if answer is not None else ""


def fallback_prompt(
    question: str,
    options: list[dict[str, str]],
    *,
    line_prefix: str = "",
    user_prompt: str = "",
) -> str:
    """Plain-text fallback when questionary fails."""
    print(f"\n{line_prefix}Question: {question}")
    if options:
        for i, opt in enumerate(options, 1):
            print(f"{line_prefix}  {i}. {opt.get('label', '')} \u2014 {opt.get('description', '')}")
        print(f"{line_prefix}  (enter a number or type your own answer)")
    raw = input(user_prompt).strip()
    if options and raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(options):
            return options[idx - 1]["label"]
    return raw
