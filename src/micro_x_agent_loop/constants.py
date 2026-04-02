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
TOOL_SEARCH_SEMANTIC_MAX_LOAD = 5
TOOL_SEARCH_DEFAULT_THRESHOLD_PERCENT = 40
TOOL_SEARCH_DEFAULT_STRATEGY = "auto"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
TOOL_SEARCH_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-haiku-3": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_000_000,
    "o3": 200_000,
    "o4": 200_000,
    "gemini-2.5": 1_000_000,
    "gemini-2.0": 1_000_000,
    "gemini-3": 1_000_000,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
    # Ollama local models
    "mistral": 32_000,
    "llama3": 128_000,
    "llama3.2": 128_000,
    "phi3": 128_000,
    "gemma2": 8_000,
}
TOOL_SEARCH_DEFAULT_CONTEXT_WINDOW = 200_000

# ---------------------------------------------------------------------------
# Sub-agents
# ---------------------------------------------------------------------------
DEFAULT_SUBAGENT_TIMEOUT = 120
DEFAULT_SUBAGENT_MAX_TURNS = 15
DEFAULT_SUBAGENT_MAX_TOKENS = 4096
DEFAULT_SUBAGENT_MODEL = ""  # empty = inherit from parent

# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
DEFAULT_SESSION_BUDGET_USD = 0.0  # 0 = no budget limit
SESSION_BUDGET_WARN_THRESHOLD = 0.8  # Warn at 80% of budget

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
DEFAULT_PER_TURN_ROUTING_COMPLEXITY_KEYWORDS = (
    "design,architect,analyze,analyse,explain why,compare,evaluate,"
    "debug,refactor,plan,implement,trade-off,tradeoff,optimise,optimize,"
    "review,critique,suggest improvements"
)

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
CHARS_TO_TOKENS_DIVISOR = 4
