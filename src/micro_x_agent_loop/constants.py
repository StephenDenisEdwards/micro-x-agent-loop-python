"""Centralised magic numbers and default values.

Every module that previously hard-coded these values now imports them from here
so a single change propagates everywhere.
"""

# ---------------------------------------------------------------------------
# Agent / AgentConfig defaults
# ---------------------------------------------------------------------------
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MAX_TOOL_RESULT_CHARS = 40_000
DEFAULT_MAX_CONVERSATION_MESSAGES = 50
DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD = 4000
MAX_TOKENS_RETRIES = 3

# ---------------------------------------------------------------------------
# AppConfig parse defaults
# ---------------------------------------------------------------------------
DEFAULT_COMPACTION_THRESHOLD_TOKENS = 80_000
DEFAULT_PROTECTED_TAIL_MESSAGES = 6
DEFAULT_MEMORY_MAX_SESSIONS = 200
DEFAULT_MEMORY_MAX_MESSAGES_PER_SESSION = 5000
DEFAULT_MEMORY_RETENTION_DAYS = 30
DEFAULT_USER_MEMORY_MAX_LINES = 200

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
COMPACTION_PREVIEW_TOTAL = 700
COMPACTION_PREVIEW_HEAD = 500
COMPACTION_PREVIEW_TAIL = 200
COMPACTION_SUMMARIZE_INPUT_CAP = 100_000
COMPACTION_SUMMARIZE_HALF_CAP = 50_000

# ---------------------------------------------------------------------------
# Tool search
# ---------------------------------------------------------------------------
TOOL_SEARCH_MAX_LOAD = 20
TOOL_SEARCH_DEFAULT_THRESHOLD_PERCENT = 40
TOOL_SEARCH_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-haiku-3": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_000_000,
    "o3": 200_000,
    "o4": 200_000,
}
TOOL_SEARCH_DEFAULT_CONTEXT_WINDOW = 200_000

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
CHARS_TO_TOKENS_DIVISOR = 4
