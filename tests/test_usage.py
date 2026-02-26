import unittest

from micro_x_agent_loop.usage import PRICING, UsageResult, estimate_cost


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


if __name__ == "__main__":
    unittest.main()
