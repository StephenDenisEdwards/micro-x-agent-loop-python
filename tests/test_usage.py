import unittest

from micro_x_agent_loop.usage import (
    PRICING,
    UsageResult,
    _lookup_pricing,
    _warned_models,
    estimate_cost,
    load_pricing_overrides,
)


class UsageResultTests(unittest.TestCase):
    def test_defaults(self) -> None:
        u = UsageResult()
        self.assertEqual(0, u.input_tokens)
        self.assertEqual(0, u.output_tokens)
        self.assertEqual(0, u.cache_creation_input_tokens)
        self.assertEqual(0, u.cache_read_input_tokens)
        self.assertEqual(0.0, u.duration_ms)
        self.assertEqual("", u.provider)
        self.assertEqual("", u.model)

    def test_frozen(self) -> None:
        u = UsageResult(input_tokens=10)
        with self.assertRaises(AttributeError):
            u.input_tokens = 20  # type: ignore[misc]

    def test_construction(self) -> None:
        u = UsageResult(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=10,
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
        )
        self.assertEqual(100, u.input_tokens)
        self.assertEqual(50, u.output_tokens)
        self.assertEqual(10, u.cache_read_input_tokens)
        self.assertEqual("anthropic", u.provider)


class EstimateCostTests(unittest.TestCase):
    def test_known_model(self) -> None:
        u = UsageResult(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
        )
        cost = estimate_cost(u)
        # input: 3.0, output: 15.0 => 18.0
        self.assertAlmostEqual(18.0, cost, places=4)

    def test_cache_tokens(self) -> None:
        u = UsageResult(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
            cache_creation_input_tokens=1_000_000,
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
        )
        cost = estimate_cost(u)
        # cache_read: 0.30, cache_create: 3.75 => 4.05
        self.assertAlmostEqual(4.05, cost, places=4)

    def test_unknown_model_returns_zero(self) -> None:
        u = UsageResult(input_tokens=1000, output_tokens=500, model="unknown-model-xyz")
        self.assertEqual(0.0, estimate_cost(u))

    def test_pricing_dict_has_entries(self) -> None:
        self.assertGreater(len(PRICING), 0)
        for key, prices in PRICING.items():
            self.assertEqual(4, len(prices), f"Key {key} should have 4 price entries")


class LoadPricingOverridesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(PRICING)
        PRICING.clear()

    def tearDown(self) -> None:
        PRICING.clear()
        PRICING.update(self._saved)

    def test_loads_model_pricing(self) -> None:
        load_pricing_overrides(
            {
                "myprovider/my-custom-model": {"input": 1.0, "output": 4.0, "cache_read": 0.5, "cache_create": 0.0},
            }
        )
        prices = _lookup_pricing("myprovider", "my-custom-model")
        self.assertIsNotNone(prices)
        self.assertEqual((1.0, 4.0, 0.5, 0.0), prices)

    def test_overwrites_existing_entry(self) -> None:
        load_pricing_overrides(
            {
                "testprov/test-model": {"input": 1.0, "output": 2.0},
            }
        )
        load_pricing_overrides(
            {
                "testprov/test-model": {"input": 99.0, "output": 99.0},
            }
        )
        prices = _lookup_pricing("testprov", "test-model")
        self.assertEqual((99.0, 99.0, 0.0, 0.0), prices)

    def test_prefix_match(self) -> None:
        load_pricing_overrides(
            {
                "myprov/my-model-v2-20260101": {"input": 2.0, "output": 8.0},
            }
        )
        prices = _lookup_pricing("myprov", "my-model-v2")
        self.assertIsNotNone(prices)
        self.assertEqual(2.0, prices[0])

    def test_cache_fields_default_to_zero(self) -> None:
        load_pricing_overrides(
            {
                "prov/cheap-model": {"input": 0.1, "output": 0.4},
            }
        )
        prices = _lookup_pricing("prov", "cheap-model")
        self.assertEqual((0.1, 0.4, 0.0, 0.0), prices)

    def test_empty_pricing_returns_none(self) -> None:
        prices = _lookup_pricing("prov", "nonexistent-model")
        self.assertIsNone(prices)

    def test_model_only_fallback(self) -> None:
        """When provider doesn't match, falls back to model portion of key."""
        load_pricing_overrides(
            {
                "anthropic/claude-test": {"input": 5.0, "output": 10.0},
            }
        )
        # Different provider, but model matches the model portion of the key
        prices = _lookup_pricing("other-provider", "claude-test")
        self.assertIsNotNone(prices)
        self.assertEqual((5.0, 10.0, 0.0, 0.0), prices)

    def test_provider_match_takes_priority(self) -> None:
        """Provider/model exact match wins over model-only fallback."""
        load_pricing_overrides(
            {
                "cheap-provider/my-model": {"input": 1.0, "output": 2.0},
                "expensive-provider/my-model": {"input": 10.0, "output": 20.0},
            }
        )
        prices = _lookup_pricing("expensive-provider", "my-model")
        self.assertEqual((10.0, 20.0, 0.0, 0.0), prices)


class UnknownModelWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_warned = set(_warned_models)
        _warned_models.clear()

    def tearDown(self) -> None:
        _warned_models.clear()
        _warned_models.update(self._saved_warned)

    def test_unknown_model_returns_zero(self) -> None:
        u = UsageResult(input_tokens=1000, output_tokens=500, model="totally-unknown-xyz")
        self.assertEqual(0.0, estimate_cost(u))

    def test_unknown_model_added_to_warned_set(self) -> None:
        model = "warn-test-model-abc"
        u = UsageResult(input_tokens=100, output_tokens=50, model=model)
        estimate_cost(u)
        self.assertIn(model, _warned_models)

    def test_unknown_provider_model_added_to_warned_set(self) -> None:
        u = UsageResult(input_tokens=100, output_tokens=50, provider="myprov", model="warn-prov-model")
        estimate_cost(u)
        self.assertIn("myprov/warn-prov-model", _warned_models)

    def test_empty_model_does_not_warn(self) -> None:
        u = UsageResult(input_tokens=100, output_tokens=50, model="")
        estimate_cost(u)
        self.assertNotIn("", _warned_models)


class EstimateCostAllModelsTests(unittest.TestCase):
    """Verify estimate_cost() produces the correct result for every model in the pricing table."""

    # Standard token counts used across all model tests.
    INPUT = 10_000
    OUTPUT = 5_000
    CACHE_READ = 50_000
    CACHE_CREATE = 2_000

    # All models from config-base.json Pricing section with their expected costs.
    # Expected cost = (INPUT*inp + OUTPUT*out + CACHE_READ*cr + CACHE_CREATE*cc) / 1_000_000
    MODELS: dict[str, tuple[str, str, float]] = {
        # key: (provider, model, expected_cost)
        "anthropic/claude-opus-4-6-20260204": ("anthropic", "claude-opus-4-6-20260204", 0.212500),
        "anthropic/claude-opus-4-5-20250918": ("anthropic", "claude-opus-4-5-20250918", 0.212500),
        "anthropic/claude-opus-4-1-20250527": ("anthropic", "claude-opus-4-1-20250527", 0.637500),
        "anthropic/claude-opus-4-20250514": ("anthropic", "claude-opus-4-20250514", 0.637500),
        "anthropic/claude-sonnet-4-6-20260204": ("anthropic", "claude-sonnet-4-6-20260204", 0.127500),
        "anthropic/claude-sonnet-4-5-20250929": ("anthropic", "claude-sonnet-4-5-20250929", 0.127500),
        "anthropic/claude-sonnet-4-5-20250514": ("anthropic", "claude-sonnet-4-5-20250514", 0.127500),
        "anthropic/claude-sonnet-4-20250514": ("anthropic", "claude-sonnet-4-20250514", 0.127500),
        "anthropic/claude-haiku-4-5-20251001": ("anthropic", "claude-haiku-4-5-20251001", 0.042500),
        "anthropic/claude-haiku-3-5-20241022": ("anthropic", "claude-haiku-3-5-20241022", 0.034000),
        "openai/gpt-4o": ("openai", "gpt-4o", 0.137500),
        "openai/gpt-4o-mini": ("openai", "gpt-4o-mini", 0.008250),
        "openai/gpt-4.1": ("openai", "gpt-4.1", 0.085000),
        "openai/gpt-4.1-mini": ("openai", "gpt-4.1-mini", 0.017000),
        "openai/gpt-4.1-nano": ("openai", "gpt-4.1-nano", 0.004250),
        "openai/o3": ("openai", "o3", 0.085000),
        "openai/o3-mini": ("openai", "o3-mini", 0.060500),
        "openai/o4-mini": ("openai", "o4-mini", 0.030250),
        "deepseek/deepseek-chat": ("deepseek", "deepseek-chat", 0.011700),
        "deepseek/deepseek-reasoner": ("deepseek", "deepseek-reasoner", 0.023450),
        "gemini/gemini-2.0-flash": ("gemini", "gemini-2.0-flash", 0.004250),
        "gemini/gemini-2.0-flash-thinking-exp": ("gemini", "gemini-2.0-flash-thinking-exp", 0.004250),
        "gemini/gemini-2.5-pro-preview-03-25": ("gemini", "gemini-2.5-pro-preview-03-25", 0.078000),
        "ollama/gemma2:2b": ("ollama", "gemma2:2b", 0.0),
        "ollama/llama3.2:3b": ("ollama", "llama3.2:3b", 0.0),
        "ollama/mistral:7b": ("ollama", "mistral:7b", 0.0),
        "ollama/phi3:mini": ("ollama", "phi3:mini", 0.0),
    }

    def setUp(self) -> None:
        """Ensure PRICING is loaded from config-base.json before each test."""
        import json
        import os

        self._saved = dict(PRICING)
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config-base.json",
        )
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        PRICING.clear()
        load_pricing_overrides(config["Pricing"])

    def tearDown(self) -> None:
        PRICING.clear()
        PRICING.update(self._saved)

    # --- Individual model tests ---

    def test_anthropic_claude_opus_4_6(self) -> None:
        self._assert_model_cost("anthropic/claude-opus-4-6-20260204")

    def test_anthropic_claude_opus_4_5(self) -> None:
        self._assert_model_cost("anthropic/claude-opus-4-5-20250918")

    def test_anthropic_claude_opus_4_1(self) -> None:
        self._assert_model_cost("anthropic/claude-opus-4-1-20250527")

    def test_anthropic_claude_opus_4(self) -> None:
        self._assert_model_cost("anthropic/claude-opus-4-20250514")

    def test_anthropic_claude_sonnet_4_6(self) -> None:
        self._assert_model_cost("anthropic/claude-sonnet-4-6-20260204")

    def test_anthropic_claude_sonnet_4_5_20250929(self) -> None:
        self._assert_model_cost("anthropic/claude-sonnet-4-5-20250929")

    def test_anthropic_claude_sonnet_4_5_20250514(self) -> None:
        self._assert_model_cost("anthropic/claude-sonnet-4-5-20250514")

    def test_anthropic_claude_sonnet_4(self) -> None:
        self._assert_model_cost("anthropic/claude-sonnet-4-20250514")

    def test_anthropic_claude_haiku_4_5(self) -> None:
        self._assert_model_cost("anthropic/claude-haiku-4-5-20251001")

    def test_anthropic_claude_haiku_3_5(self) -> None:
        self._assert_model_cost("anthropic/claude-haiku-3-5-20241022")

    def test_openai_gpt_4o(self) -> None:
        self._assert_model_cost("openai/gpt-4o")

    def test_openai_gpt_4o_mini(self) -> None:
        self._assert_model_cost("openai/gpt-4o-mini")

    def test_openai_gpt_4_1(self) -> None:
        self._assert_model_cost("openai/gpt-4.1")

    def test_openai_gpt_4_1_mini(self) -> None:
        self._assert_model_cost("openai/gpt-4.1-mini")

    def test_openai_gpt_4_1_nano(self) -> None:
        self._assert_model_cost("openai/gpt-4.1-nano")

    def test_openai_o3(self) -> None:
        self._assert_model_cost("openai/o3")

    def test_openai_o3_mini(self) -> None:
        self._assert_model_cost("openai/o3-mini")

    def test_openai_o4_mini(self) -> None:
        self._assert_model_cost("openai/o4-mini")

    def test_deepseek_chat(self) -> None:
        self._assert_model_cost("deepseek/deepseek-chat")

    def test_deepseek_reasoner(self) -> None:
        self._assert_model_cost("deepseek/deepseek-reasoner")

    def test_gemini_2_0_flash(self) -> None:
        self._assert_model_cost("gemini/gemini-2.0-flash")

    def test_gemini_2_0_flash_thinking_exp(self) -> None:
        self._assert_model_cost("gemini/gemini-2.0-flash-thinking-exp")

    def test_gemini_2_5_pro_preview(self) -> None:
        self._assert_model_cost("gemini/gemini-2.5-pro-preview-03-25")

    def test_ollama_gemma2_2b(self) -> None:
        self._assert_model_cost("ollama/gemma2:2b")

    def test_ollama_llama3_2_3b(self) -> None:
        self._assert_model_cost("ollama/llama3.2:3b")

    def test_ollama_mistral_7b(self) -> None:
        self._assert_model_cost("ollama/mistral:7b")

    def test_ollama_phi3_mini(self) -> None:
        self._assert_model_cost("ollama/phi3:mini")

    # --- Completeness guard ---

    def test_every_config_model_has_a_test(self) -> None:
        """Fail if a model exists in config-base.json Pricing but has no corresponding test."""
        config_keys = set(PRICING.keys())
        tested_keys = set(self.MODELS.keys())
        missing = config_keys - tested_keys
        self.assertEqual(
            set(),
            missing,
            f"Models in config Pricing section without a corresponding test: {missing}",
        )

    def test_no_extra_test_models(self) -> None:
        """Fail if a test references a model not present in the config Pricing section."""
        config_keys = set(PRICING.keys())
        tested_keys = set(self.MODELS.keys())
        extra = tested_keys - config_keys
        self.assertEqual(
            set(),
            extra,
            f"Test references models not in config Pricing section: {extra}",
        )

    # --- Helper ---

    def _assert_model_cost(self, key: str) -> None:
        provider, model, expected = self.MODELS[key]
        usage = UsageResult(
            input_tokens=self.INPUT,
            output_tokens=self.OUTPUT,
            cache_read_input_tokens=self.CACHE_READ,
            cache_creation_input_tokens=self.CACHE_CREATE,
            provider=provider,
            model=model,
        )
        cost = estimate_cost(usage)
        self.assertAlmostEqual(
            expected,
            cost,
            places=6,
            msg=f"Cost mismatch for {key}: expected {expected}, got {cost}",
        )


if __name__ == "__main__":
    unittest.main()
