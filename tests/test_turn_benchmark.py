import unittest
from pokato.analysis.turn_benchmark import benchmark_case


class TurnBenchmarkTests(unittest.TestCase):
    def test_short_call_diagnostics_are_reproducible_and_have_exact_mass(self):
        first = benchmark_case("short-allin", draws=4)
        second = benchmark_case("short-allin", draws=4)
        for key in ("point_seconds", "sensitivity_seconds"):
            first.pop(key)
            second.pop(key)
        self.assertEqual(first, second)
        self.assertEqual(first["river_cards"], 44)
        self.assertEqual(first["enumerated_deals"], 44)
        self.assertAlmostEqual(first["card_probability_mass"], 1)
        self.assertAlmostEqual(first["actions"]["Call"], 260*first["showdown_equity"]-30)
        self.assertEqual(first["sensitivity"]["quadrature_shift"], 0)


if __name__ == "__main__":
    unittest.main()
