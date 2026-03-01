import sys
from datetime import datetime

_USER_MEMORY_GUIDANCE = """\

# User Memory Guidance

You have persistent memory in the user memory directory. As you work:
- Save stable patterns confirmed across interactions to MEMORY.md
- Save key architectural decisions, important file paths, project structure
- Save user preferences for workflow, tools, and communication style
- Save solutions to recurring problems
- Do NOT save session-specific context or in-progress work
- Do NOT save speculative conclusions from a single observation
- When the user explicitly asks you to remember something, save it immediately\
"""


_CONCISE_OUTPUT_DIRECTIVE = """\


IMPORTANT: Minimize output tokens. Use bullet points, not paragraphs. Omit pleasantries and \
filler. When reporting tool results, state only the key findings — do not echo raw data back. \
For file operations, confirm success in one line. Target maximum 200 words per response unless \
the user asks for detail."""


def get_system_prompt(
    *,
    user_memory: str = "",
    user_memory_enabled: bool = False,
    concise_output_enabled: bool = False,
    working_directory: str | None = None,
) -> str:
    is_windows = sys.platform == "win32"
    if is_windows:
        platform_line = (
            "You are running on Windows. Use Windows shell commands (dir, type, copy, etc.) "
            "— not Unix commands (ls, cat, cp, head, tail, etc.)."
        )
    else:
        platform_line = "You are running on a Unix-like system. Use standard shell commands."

    prompt = f"""\
You are a helpful AI assistant with access to tools. You can execute shell commands, \
read files, and write files to help the user with their tasks.

{platform_line}

Today's date is {{current_date}}.

When the user asks you to do something, use the available tools to accomplish it. \
Think step by step about what tools you need to use, then use them.

When writing large files, break the content into sections: use write_file to create the file \
with the first section, then use append_file to add the remaining sections. This avoids \
hitting output token limits.

If a tool call fails, read the error message carefully and try a different approach.

Be concise in your responses. When you've completed a task, briefly summarize what you did.\
"""
    if working_directory:
        prompt += f"\n\nYour working directory is: {working_directory}\n"
        prompt += "All relative file paths and shell commands should be relative to this directory. "
        prompt += "When the user asks to list files, read files, or perform operations without "
        prompt += "specifying a path, use this directory as the default."
    if user_memory:
        prompt += f"\n\n# User Memory\n\n{user_memory}"
    if user_memory_enabled:
        prompt += _USER_MEMORY_GUIDANCE
    if concise_output_enabled:
        prompt += _CONCISE_OUTPUT_DIRECTIVE
    return prompt


def resolve_system_prompt(template: str) -> str:
    """Replace ``{current_date}`` with the current local date.

    Called before each API request so the date is always accurate,
    even for long-running sessions that span midnight.
    """
    today = datetime.now().strftime("%A, %B %d, %Y")
    return template.replace("{current_date}", today)
