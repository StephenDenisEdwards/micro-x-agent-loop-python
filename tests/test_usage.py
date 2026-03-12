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
        for model, prices in PRICING.items():
            self.assertEqual(4, len(prices), f"Model {model} should have 4 price entries")


class LoadPricingOverridesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(PRICING)
        PRICING.clear()

    def tearDown(self) -> None:
        PRICING.clear()
        PRICING.update(self._saved)

    def test_loads_model_pricing(self) -> None:
        load_pricing_overrides({
            "my-custom-model": {"input": 1.0, "output": 4.0, "cache_read": 0.5, "cache_create": 0.0},
        })
        prices = _lookup_pricing("my-custom-model")
        self.assertIsNotNone(prices)
        self.assertEqual((1.0, 4.0, 0.5, 0.0), prices)

    def test_overwrites_existing_entry(self) -> None:
        load_pricing_overrides({
            "test-model": {"input": 1.0, "output": 2.0},
        })
        load_pricing_overrides({
            "test-model": {"input": 99.0, "output": 99.0},
        })
        prices = _lookup_pricing("test-model")
        self.assertEqual((99.0, 99.0, 0.0, 0.0), prices)

    def test_prefix_match(self) -> None:
        load_pricing_overrides({
            "my-model-v2-20260101": {"input": 2.0, "output": 8.0},
        })
        prices = _lookup_pricing("my-model-v2")
        self.assertIsNotNone(prices)
        self.assertEqual(2.0, prices[0])

    def test_cache_fields_default_to_zero(self) -> None:
        load_pricing_overrides({
            "cheap-model": {"input": 0.1, "output": 0.4},
        })
        prices = _lookup_pricing("cheap-model")
        self.assertEqual((0.1, 0.4, 0.0, 0.0), prices)

    def test_empty_pricing_returns_none(self) -> None:
        prices = _lookup_pricing("nonexistent-model")
        self.assertIsNone(prices)


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

    def test_empty_model_does_not_warn(self) -> None:
        u = UsageResult(input_tokens=100, output_tokens=50, model="")
        estimate_cost(u)
        self.assertNotIn("", _warned_models)


if __name__ == "__main__":
    unittest.main()
