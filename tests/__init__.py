import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Load standard pricing data so tests using estimate_cost() with known model names
# get correct results. In production this is loaded from config.json at startup.
# This runs for both pytest and `unittest discover` (conftest.py is pytest-only).
from micro_x_agent_loop.usage import PRICING, load_pricing_overrides  # noqa: E402

if not PRICING:
    load_pricing_overrides(
        {
            "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_create": 3.75},
            "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_create": 3.75},
            "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_create": 1.25},
            "gpt-4o": {"input": 2.50, "output": 10.0, "cache_read": 1.25, "cache_create": 0.0},
            "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cache_read": 0.10, "cache_create": 0.0},
        }
    )
