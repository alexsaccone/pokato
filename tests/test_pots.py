from dataclasses import replace
import random
import unittest
from pokato.core.cards import DECK, evaluate
from pokato.core.pots import build_pots, payout
from pokato.analysis.history import Profile
from pokato.analysis.pot_equity import calculate_pots
from pokato.analysis.ranges import parse_range
from pokato.analysis.coach import analyze
from pokato.vision.reader import Observation, Seat
from reference_poker import rank_seven, chip_payouts


class PotTests(unittest.TestCase):
    def test_evaluator_against_independent_five_card_oracle(self):
        rng = random.Random(73)
        for _ in range(500):
            cards = rng.sample(DECK, 7)
            self.assertEqual(evaluate(cards), rank_seven(cards))

    def test_payouts_against_independent_chip_oracle(self):
        rng = random.Random(6)
        for _ in range(250):
            contributions = [rng.randint(1, 30) for _ in range(6)]
            # Preserve a deepest live player, ensuring every tier is contestable.
            deepest = contributions.index(max(contributions))
            folded = {i for i in range(6) if i != deepest and rng.random() < .35}
            ranks = {i: (rng.randrange(3),) for i in range(6)}
            button = rng.randrange(6)
            totals = [0] * 6
            for pot in build_pots(contributions, folded):
                for seat, award in payout(pot, ranks, button, 6).items():
                    totals[seat] += award
            self.assertEqual(totals, chip_payouts(contributions, folded, ranks, button))
            self.assertEqual(sum(totals), sum(contributions))

    def test_hero_loses_main_but_wins_side_pot(self):
        ranges = {1: parse_range("AsAh"), 2: parse_range("QsQh")}
        result = calculate_pots(("Ks", "Kh"), tuple("2c 3d 7h 9s Tc".split()),
                                [Profile(1), Profile(2)], [200, 50, 200], ranges=ranges)
        self.assertTrue(result.equity.exact)
        self.assertEqual([p.amount for p in result.pots], [150, 300])
        self.assertEqual(result.award, 300)
        self.assertAlmostEqual(result.equity.share, 2 / 3)
        self.assertEqual(result.error, 0)

    def test_dead_money_refund_and_blocked_range(self):
        result = calculate_pots(("As", "Ks"), tuple("Qs Js Ts 2c 3d".split()),
                                [Profile(1)], [200, 100, 50], folded={2}, ranges={1: parse_range("AhAd")})
        self.assertEqual(sum(p.amount for p in result.pots), 350)
        self.assertEqual(result.award, 350)
        self.assertTrue(result.pots[-1].refund)
        with self.assertRaisesRegex(ValueError, "empty"):
            calculate_pots(("As", "Ks"), tuple("Qs Js Ts 2c 3d".split()),
                           [Profile(1)], [100, 100], ranges={1: parse_range("AsAh")})

    def test_side_pot_call_ev_and_no_single_threshold(self):
        seats = (Seat("A", 850, 50, 150), Seat("I", 0, 50, 50), Seat("A", 800, 100, 200),
                 Seat("F", 1000, 0, 0), Seat("F", 1000, 0, 0), Seat("F", 1000, 0, 0))
        o = Observation(1, "R", 0, 0, 400, 50, 200, 900, ("Ks", "Kh"),
                        tuple("2c 3d 7h 9s Tc".split()), seats, (), 1.0)
        advice = analyze(o, [Profile(i) for i in range(6)], samples=100,
                         ranges={1: parse_range("AsAh"), 2: parse_range("QsQh")})
        self.assertEqual(next(a.ev for a in advice.actions if a.label == "Call"), 250)
        self.assertFalse(advice.pot_odds_valid)
        self.assertEqual(len(advice.pots), 2)

    def test_sampled_turn_payout_matches_independent_runout_enumeration(self):
        hero, villain = ("As", "Ah"), ("Ks", "Kh")
        board = tuple("2c 3d 7h 9s".split())
        payouts = []
        for river in DECK:
            if river not in hero + villain + board:
                ranks = {0: rank_seven(hero + board + (river,)),
                         1: rank_seven(villain + board + (river,))}
                payouts.append(chip_payouts([100, 100], set(), ranks, 0)[0])
        expected = sum(payouts) / len(payouts)
        sampled = calculate_pots(hero, board, [Profile(1)], [100, 100],
                                 ranges={1: parse_range("KsKh")}, samples=8000, seed=34)
        self.assertFalse(sampled.equity.exact)
        self.assertLess(abs(sampled.award - expected), 4 * sampled.error)
