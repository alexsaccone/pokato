import random
import unittest
from pokato.core.cards import evaluate
from pokato.core.game import Game


class CardsTests(unittest.TestCase):
    def test_wheel_and_board_tie(self):
        self.assertEqual(evaluate("As 2d 3h 4c 5s Kd Qc".split()), (4, 5))
        board = "As Ks Qs Js Ts".split()
        self.assertEqual(evaluate(board + ["2c", "3c"]), evaluate(board + ["Ah", "Ad"]))

    def test_two_trips_and_flush_kickers(self):
        self.assertEqual(evaluate("As Ah Ad Ks Kh Kd 2c".split()), (6, 14, 13))
        self.assertGreater(evaluate("As Js 9s 5s 3s 2d 4c".split()),
                           evaluate("Ks Js 9s 5s 3s 2d 4c".split()))

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(["As"] * 5)


class GameTests(unittest.TestCase):
    def test_random_legal_hands_conserve_chips(self):
        rng = random.Random(12)
        g = Game(stacks=[50, 70, 130, 210, 330, 500])
        for _ in range(60):
            total = sum(p.stack for p in g.players)
            rebuy = sum(1000 for p in g.players if not p.stack)
            g.new_hand()
            actions = 0
            while g.actor >= 0:
                legal = g.legal()
                choice = rng.randrange(4)
                if choice == 0:
                    g.act("F")
                elif choice == 1 and legal["min_raise"]:
                    g.act("R", rng.randint(legal["min_raise"], legal["max_raise"]))
                else:
                    g.act("K" if legal["check"] else "C")
                actions += 1
                self.assertLess(actions, 200)
                self.assertEqual(sum(p.stack for p in g.players) + g.pot, total + rebuy)
            self.assertTrue(all(p.stack >= 0 for p in g.players))

    def test_big_blind_gets_option(self):
        g = Game()
        g.new_hand()
        for _ in range(5):
            g.act("C")
        self.assertEqual(g.actor, 2)
        self.assertTrue(g.legal()["check"])
        g.act("K")
        self.assertEqual(g.street, "F")

    def test_illegal_raise_does_not_mutate(self):
        g = Game()
        g.new_hand()
        before = (g.pot, g.actor, len(g.events))
        with self.assertRaises(ValueError):
            g.act("R", 11)
        self.assertEqual(before, (g.pot, g.actor, len(g.events)))

    def test_short_all_in_does_not_reopen_betting(self):
        g = Game(stacks=[1000, 1000, 1000, 1000, 45, 1000])
        g.new_hand()
        g.act("R", 30)
        g.act("R", 45)
        for _ in range(4):
            g.act("C")
        self.assertEqual(g.actor, 3)
        self.assertEqual(g.legal()["call"], 15)
        self.assertEqual(g.legal()["min_raise"], 0)

    def test_cumulative_short_raises_reopen_betting(self):
        g = Game(stacks=[1000, 1000, 1000, 1000, 45, 60])
        g.new_hand()
        g.act("R", 30)
        g.act("R", 45)
        g.act("R", 60)
        for _ in range(3):
            g.act("C")
        self.assertEqual(g.actor, 3)
        self.assertEqual(g.legal()["min_raise"], 80)

    def test_side_pots_and_uncalled_refund(self):
        g = Game()
        g.new_hand()
        g.board = "2c 3d 7h 9s Tc".split()
        for i, p in enumerate(g.players):
            p.folded = i >= 3
            p.invested = (i + 1) * 100 if i < 3 else 0
            p.stack = 1000 - p.invested
        for i, cards in enumerate(("As Ah", "Ks Kh", "Qs Qh")):
            g.players[i].hole = cards.split()
        g._settle()
        self.assertEqual([p.stack for p in g.players], [1200, 1000, 800, 1000, 1000, 1000])


if __name__ == "__main__":
    unittest.main()
