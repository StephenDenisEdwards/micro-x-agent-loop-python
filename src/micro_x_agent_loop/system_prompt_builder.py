"""Consolidates system prompt construction from feature flags.

Replaces the scattered ``self._system_prompt += _DIRECTIVE`` pattern
in ``Agent.__init__`` with a single-pass builder.
"""

from __future__ import annotations

from micro_x_agent_loop.system_prompt import (
    _ASK_USER_DIRECTIVE,
    _SUBAGENT_DIRECTIVE,
    _TOOL_SEARCH_DIRECTIVE,
)


def build_system_prompt(
    *,
    base_prompt: str,
    tool_search_active: bool = False,
    ask_user_enabled: bool = False,
    sub_agents_enabled: bool = False,
) -> str:
    """Append optional directives to the base system prompt in one pass.

    Parameters
    ----------
    base_prompt:
        The core system prompt returned by ``get_system_prompt()``.
    tool_search_active:
        Append the tool-discovery directive.
    ask_user_enabled:
        Append the ``ask_user`` usage directive.
    sub_agents_enabled:
        Append the sub-agent delegation directive.
    """
    prompt = base_prompt
    if tool_search_active:
        prompt += _TOOL_SEARCH_DIRECTIVE
    if ask_user_enabled:
        prompt += _ASK_USER_DIRECTIVE
    if sub_agents_enabled:
        prompt += _SUBAGENT_DIRECTIVE
    return prompt
