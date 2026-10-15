import unittest
from pokato.analysis.benchmark import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_reproducible_paired_evaluation_reports_uncertainty(self):
        report = benchmark(pairs=80, seed=31)
        self.assertEqual(report, benchmark(pairs=80, seed=31))
        for policy in report["policies"].values():
            result = policy["adapted_minus_baseline_chips"]
            low, high = result["paired_95_interval"]
            self.assertEqual(result["pairs"], 80)
            self.assertLessEqual(low, result["mean_delta"])
            self.assertGreaterEqual(high, result["mean_delta"])
            self.assertGreater(policy["brier_improvement"]["mean_delta"], 0)
