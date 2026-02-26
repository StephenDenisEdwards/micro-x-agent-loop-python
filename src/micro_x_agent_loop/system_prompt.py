from datetime import datetime, timezone

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
) -> str:
    now = datetime.now(timezone.utc)
    today = now.strftime("%A, %B %d, %Y")
    prompt = f"""\
You are a helpful AI assistant with access to tools. You can execute bash commands, \
read files, and write files to help the user with their tasks.

Today's date is {today} (UTC).

When the user asks you to do something, use the available tools to accomplish it. \
Think step by step about what tools you need to use, then use them.

When writing large files, break the content into sections: use write_file to create the file \
with the first section, then use append_file to add the remaining sections. This avoids \
hitting output token limits.

If a tool call fails, read the error message carefully and try a different approach.

Be concise in your responses. When you've completed a task, briefly summarize what you did.\
"""
    if user_memory:
        prompt += f"\n\n# User Memory\n\n{user_memory}"
    if user_memory_enabled:
        prompt += _USER_MEMORY_GUIDANCE
    if concise_output_enabled:
        prompt += _CONCISE_OUTPUT_DIRECTIVE
    return prompt
