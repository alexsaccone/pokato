from dataclasses import replace
import math
import statistics
import unittest
from pokato.analysis.bayes import SessionModel, ResponseCount
from pokato.analysis.history import Profile
from pokato.analysis.ranges import parse_range
from pokato.analysis.turn import TurnTree
from pokato.analysis.uncertainty import DrawnModel, compressed_prior, turn_sensitivity
from test_turn import fixture


class UncertaintyTests(unittest.TestCase):
    def test_policy_draws_are_coherent_and_reproducible(self):
        base = SessionModel(1)
        model = DrawnModel(base, 19)
        p = model.posterior("T", 10, 100)
        self.assertIs(p, model.posterior("T", 20, 100))
        self.assertEqual(p, DrawnModel(base, 19).posterior("T", 10, 100))
        self.assertNotEqual(p.mean, model.posterior("R", 10, 100).mean)
        self.assertAlmostEqual(sum(p.mean), 1)
        self.assertTrue(all(0 < rate < 1 for rate in p.mean))

    def test_dirichlet_draw_moments_and_more_evidence_shrinks_uncertainty(self):
        cold = SessionModel(1)
        dense = SessionModel(1, tuple(ResponseCount("T", "small", a, n)
                                     for a, n in zip(("F", "C", "R"), (1000, 1100, 300))))
        rows = [[DrawnModel(model, i).posterior("T", 10, 100).mean[0] for i in range(1500)]
                for model in (cold, dense)]
        expected = cold.posterior("T", 10, 100).mean[0]
        self.assertAlmostEqual(statistics.mean(rows[0]), expected, delta=.015)
        self.assertAlmostEqual(statistics.mean(rows[1]), expected, delta=.005)
        self.assertLess(statistics.variance(rows[1]), statistics.variance(rows[0])/30)

    def test_sensitivity_is_deterministic_finite_and_distinguishes_sampling_error(self):
        o = fixture(stack=30)
        profile = Profile(1)
        tree = TurnTree(o, profile, ranges={1: parse_range("AsAh, QsQh")})
        result = tree.run()
        first = turn_sensitivity(tree, result, profile, draws=12)
        second = turn_sensitivity(tree, result, profile, draws=12)
        self.assertEqual(first, second)
        self.assertEqual(first.hands, 2)
        self.assertAlmostEqual(first.quadrature_shift, 0)
        self.assertAlmostEqual(sum(a.best_fraction for a in first.actions), 1)
        self.assertTrue(all(math.isfinite(a.low) and a.high >= a.low for a in first.actions))
        self.assertTrue(any(a.high-a.low > .1 for a in first.actions))
        self.assertIn("policies", first.summary(max(result.values, key=lambda a: a[1])[0]))

    def test_terminal_explicit_range_has_no_response_policy_ev_spread(self):
        o = fixture(facing=30, stack=30)
        seats = list(o.seats)
        seats[1] = replace(seats[1], status="I", stack=0)
        o = replace(o, seats=tuple(seats), minimum=0, maximum=0)
        profile = Profile(1)
        tree = TurnTree(o, profile, ranges={1: parse_range("QsQh")})
        sensitivity = turn_sensitivity(tree, tree.run(), profile, draws=8)
        for action in sensitivity.actions:
            self.assertAlmostEqual(action.low, action.high)

    def test_policy_ev_bands_narrow_with_matching_abundant_evidence(self):
        counts = []
        for street in ("T", "R"):
            for bucket in ("open", "small", "medium", "large"):
                actions, amounts = (("K", "R"), (1800, 600)) if bucket == "open" else (("F", "C", "R"), (1000, 1100, 300))
                counts.extend(ResponseCount(street, bucket, a, n) for a, n in zip(actions, amounts))
        widths = []
        for model in (SessionModel(1), SessionModel(1, tuple(counts))):
            profile = Profile(1)
            tree = TurnTree(fixture(stack=30), profile, ranges={1: parse_range("AsAh, QsQh")}, model=model)
            result = turn_sensitivity(tree, tree.run(), profile, draws=8)
            widths.append(sum(a.high-a.low for a in result.actions))
        self.assertLess(widths[1], widths[0]/3)

    def test_range_quadrature_preserves_blockers_and_weight_mass(self):
        tree = TurnTree(fixture(), Profile(1))
        first = compressed_prior(tree, 32, 31)
        self.assertEqual(first, compressed_prior(tree, 32, 31))
        self.assertLessEqual(len(first.weights), 32)
        self.assertAlmostEqual(sum(w for h, w in first.weights), 1)
        self.assertTrue(all(not set(h).intersection(tree.o.hole+tree.o.board) for h, w in first.weights))
        with self.assertRaises(ValueError):
            compressed_prior(tree, 0, 31)


if __name__ == "__main__":
    unittest.main()
