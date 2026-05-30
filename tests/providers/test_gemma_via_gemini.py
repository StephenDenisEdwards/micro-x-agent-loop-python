"""Phase 1 of PLAN-gemma-model-support — hosted Gemma 3 via the existing
GeminiProvider.  Two offline checks (data integrity) plus two live smoke
tests gated on ``GEMINI_API_KEY`` so the suite stays runnable without
network access.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from typing import Any

from micro_x_agent_loop.app_config import load_json_config, parse_app_config
from micro_x_agent_loop.tool_search import _get_context_window


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


class GemmaContextWindowLookupTests(unittest.TestCase):
    """Phase 1 §4.4 — prefix matches on TOOL_SEARCH_CONTEXT_WINDOWS."""

    def test_ollama_gemma3_prefix_resolves(self) -> None:
        self.assertEqual(128_000, _get_context_window("gemma3:4b"))
        self.assertEqual(128_000, _get_context_window("gemma3:12b"))
        self.assertEqual(128_000, _get_context_window("gemma3:27b"))

    def test_hosted_gemma3_variants_resolve(self) -> None:
        self.assertEqual(32_000, _get_context_window("gemma-3-1b-it"))
        self.assertEqual(128_000, _get_context_window("gemma-3-4b-it"))
        self.assertEqual(128_000, _get_context_window("gemma-3-12b-it"))
        self.assertEqual(128_000, _get_context_window("gemma-3-27b-it"))

    def test_orieg_fine_tune_resolves(self) -> None:
        self.assertEqual(128_000, _get_context_window("orieg/gemma3-tools:4b-ft"))

    def test_legacy_gemma2_unchanged(self) -> None:
        """Phase 1 must not regress the existing gemma2 entry."""
        self.assertEqual(8_000, _get_context_window("gemma2:2b"))


class GemmaPricingEntriesCompleteTests(unittest.TestCase):
    """Phase 1 §4.3 — every Gemma model in the Gemma profile configs must
    have a pricing entry so the unknown-model warning does not fire.
    """

    GEMMA_PROFILE_NAMES = (
        "config-standard-gemma-cloud.json",
        "config-standard-ollama-gemma2.json",
        "config-standard-ollama-gemma2-hybrid.json",
        "config-standard-ollama-gemma3.json",
    )

    def _load_pricing(self) -> dict[str, dict[str, float]]:
        with open(_REPO_ROOT / "config-base.json") as f:
            data = json.load(f)
        pricing = data["Pricing"]
        self.assertIsInstance(pricing, dict)
        return pricing  # type: ignore[no-any-return]

    def _model_keys_for_profile(self, profile_name: str) -> set[str]:
        path = _REPO_ROOT / profile_name
        if not path.exists():
            return set()
        data, _ = load_json_config(str(path))
        cfg = parse_app_config(data)
        keys: set[str] = set()
        if cfg.model:
            keys.add(f"{cfg.provider_name}/{cfg.model}")
        # Only check sub-agent / compaction keys if those features are
        # actually enabled — base inheritance leaves stale model IDs in
        # the dataclass for disabled features, which the agent never
        # touches at runtime.
        if cfg.sub_agents_enabled and cfg.sub_agent_provider and cfg.sub_agent_model:
            keys.add(f"{cfg.sub_agent_provider}/{cfg.sub_agent_model}")
        if (
            cfg.compaction_strategy_name == "summarize"
            and cfg.compaction_provider
            and cfg.compaction_model
        ):
            keys.add(f"{cfg.compaction_provider}/{cfg.compaction_model}")
        return keys

    def test_every_model_in_gemma_profiles_has_pricing(self) -> None:
        pricing = self._load_pricing()
        for profile_name in self.GEMMA_PROFILE_NAMES:
            with self.subTest(profile=profile_name):
                for key in self._model_keys_for_profile(profile_name):
                    self.assertIn(
                        key,
                        pricing,
                        f"{profile_name} references {key!r} but no Pricing entry exists",
                    )

    def test_pricing_entries_have_complete_shape(self) -> None:
        pricing = self._load_pricing()
        required_keys = {"input", "output", "cache_read", "cache_create"}
        for key, entry in pricing.items():
            if "/gemma" not in key and "/orieg/gemma3" not in key:
                continue
            with self.subTest(model=key):
                self.assertEqual(
                    required_keys,
                    set(entry.keys()),
                    f"{key} pricing entry is missing one of {required_keys}",
                )


@unittest.skipUnless(_GEMINI_KEY, "Live smoke test — set GEMINI_API_KEY to enable")
class GemmaViaGeminiLiveSmokeTests(unittest.TestCase):
    """Hits the real Google AI Studio endpoint. Gated on GEMINI_API_KEY.

    These tests confirm that the existing GeminiProvider passes through
    ``model="gemma-3-*-it"`` IDs and that the SDK surfaces both text deltas
    and FunctionCall parts unchanged — i.e. **no provider code change is
    required for Phase 1**.
    """

    def test_streams_text_for_chat_prompt(self) -> None:
        from micro_x_agent_loop.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key=_GEMINI_KEY)

        async def _run() -> Any:
            return await provider.stream_chat(
                model="gemma-3-4b-it",
                max_tokens=64,
                temperature=0.0,
                system_prompt="",
                messages=[{"role": "user", "content": "Reply with only the word OK."}],
                tools=[],
            )

        message, tool_use_blocks, stop_reason, usage = asyncio.run(_run())
        self.assertEqual("assistant", message["role"])
        self.assertEqual([], tool_use_blocks)
        self.assertIn(stop_reason, ("end_turn", "max_tokens"))
        self.assertGreater(getattr(usage, "input_tokens", 0), 0)

    def test_returns_function_call_for_tool_prompt(self) -> None:
        from micro_x_agent_loop.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key=_GEMINI_KEY)
        tools = [
            {
                "name": "get_weather",
                "description": "Get the current weather for a city.",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ]

        async def _run() -> Any:
            return await provider.stream_chat(
                model="gemma-3-12b-it",
                max_tokens=128,
                temperature=0.0,
                system_prompt="",
                messages=[
                    {"role": "user", "content": "What's the weather in Tokyo? Use the tool."}
                ],
                tools=tools,
            )

        _message, tool_use_blocks, stop_reason, _usage = asyncio.run(_run())
        # If Gemma decided to call the tool, the wire format must be the
        # internal {type, id, name, input} shape. If it answered in text
        # instead (4B variants sometimes do), at least confirm no schema
        # rejection happened — the call completed without raising.
        if tool_use_blocks:
            block = tool_use_blocks[0]
            self.assertEqual("get_weather", block["name"])
            self.assertIn("city", block["input"])
            self.assertEqual("tool_use", stop_reason)


if __name__ == "__main__":
    unittest.main()
