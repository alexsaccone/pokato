import random
import unittest
from pokato.analysis.ranges import parse_range, Distribution, joint_holes


class RangeTests(unittest.TestCase):
    def test_classes_weights_and_plus(self):
        self.assertEqual(len(parse_range("AA").weights), 6)
        self.assertEqual(len(parse_range("AKs").weights), 4)
        self.assertEqual(len(parse_range("AKo").weights), 12)
        self.assertEqual(len(parse_range("QQ+, ATs+").weights), 18 + 16)
        r = parse_range("AA:0.5 AsAh:0")
        self.assertEqual(len(r.weights), 5)
        self.assertTrue(all(weight == 0.5 for _, weight in r.weights))

    def test_blockers_and_invalid_input(self):
        self.assertEqual(len(parse_range("AA").available(["As"])), 3)
        for expression in ("", "AsAs", "KAo", "AAs", "AA:nan", "AA:1.1", "garbage", "AA:0"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                parse_range(expression)

    def test_impossible_joint_ranges_fail(self):
        d = Distribution(parse_range("AsAh").weights)
        with self.assertRaisesRegex(ValueError, "conflict"):
            joint_holes(random.Random(1), [d, d])

    def test_joint_sampling_matches_product_weights(self):
        a = Distribution(parse_range("AsAh, KsKh").weights)
        b = Distribution(parse_range("AsAh:0.5, QsQh").weights)
        rng = random.Random(8)
        # Three compatible deals: weights 1, .5, 1. Therefore P(A=AA)=.4.
        hits = sum("As" in joint_holes(rng, [a, b])[0] for _ in range(12000))
        self.assertAlmostEqual(hits / 12000, 0.4, delta=0.02)
