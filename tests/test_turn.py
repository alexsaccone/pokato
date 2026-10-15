from copy import deepcopy
from dataclasses import replace
import math
import random
import unittest
from pokato.analysis.bayes import SessionModel
from pokato.analysis.history import Profile
from pokato.analysis.ranges import parse_range
from pokato.analysis.river import UnsupportedRiver
from pokato.analysis.turn import TurnTree
from pokato.core.cards import DECK
from pokato.core.game import Game, Event
from pokato.vision.reader import Observation, Seat, Reader
from pokato.simulator.render import render
from reference_poker import rank_seven as reference_rank
from test_river import PassiveModel


def fixture(hero=("Ks", "Kh"), facing=0, stack=300, button=0):
    seats = (Seat("A", stack, 0, 100), Seat("A", stack-facing, facing, 100+facing),
             *(Seat("F", 1000, 0, 0) for _ in range(4)))
    return Observation(1, "T", 0, button, 200+facing, facing, 2*facing if facing else 10,
                       stack, hero, tuple("Ac 2d 3h 7s".split()), seats, (), 1.)


class TurnTests(unittest.TestCase):
    def test_blocker_correct_chance_mass_and_conditional_beliefs(self):
        tree = TurnTree(fixture(), Profile(1), ranges={1: parse_range("AsAh:0.25, QsQh")})
        rows = list(tree.chance(tree.belief))
        self.assertEqual(len(rows), 46)
        self.assertAlmostEqual(math.fsum(p for c, p, b in rows), 1)
        for card, probability, belief in rows:
            self.assertAlmostEqual(sum(belief), 1)
            for hole, weight in zip(tree.holes, belief):
                if card in hole:
                    self.assertEqual(weight, 0)
        self.assertAlmostEqual(next(p for c, p, b in rows if c == "As"), .8/44)
        self.assertAlmostEqual(next(p for c, p, b in rows if c == "4c"), 1/44)

    def test_passive_tree_matches_independent_full_runout_enumeration(self):
        o = fixture()
        tree = TurnTree(o, Profile(1), ranges={1: parse_range("AsAh:0.25, QsQh")}, model=PassiveModel(), river_cap=0)
        result = tree.run()
        expected = 0.
        for hole, weight in zip(tree.holes, tree.belief):
            deck = [c for c in DECK if c not in o.hole + o.board + hole]
            for card in deck:
                own = reference_rank(o.hole + o.board + (card,))
                villain = reference_rank(hole + o.board + (card,))
                expected += weight / 44 * (200 if own > villain else 100 if own == villain else 0)
        self.assertAlmostEqual(dict(result.values)["Check"], expected)
        self.assertAlmostEqual(sum(r.probability*r.share for r in result.runouts), expected/200)
        self.assertTrue(all(math.isfinite(ev) for label, ev in result.values))

    def test_mixed_belief_does_not_choose_with_hidden_cards(self):
        o = fixture()
        mixed = TurnTree(o, Profile(1), ranges={1: parse_range("AsAh, QsQh")}, model=PassiveModel()).run()
        perfect = []
        for hole in ("AsAh", "QsQh"):
            result = TurnTree(o, Profile(1), ranges={1: parse_range(hole)}, model=PassiveModel()).run()
            perfect.append(max(ev for label, ev in result.values))
        self.assertLess(max(ev for label, ev in mixed.values), sum(perfect)/2 - 1)

    def test_public_belief_choices_and_position(self):
        # Future actor order follows the button, independently of who
        # closed the turn. New-street betting rights are reset.
        o = replace(fixture(), board=tuple("2c 3d 4h 5s".split()), hole=("As", "Ah"))
        tree = TurnTree(o, Profile(1), ranges={1: parse_range("AcAd, KcKd")}, model=PassiveModel())
        result = tree.run()
        self.assertGreaterEqual(dict(result.values)["Check"], 100)
        state = tree.river_state(replace(tree.root, pending=()))
        self.assertEqual(state.actor, 1)  # seat 1 acts after button 0
        self.assertEqual(state.bets, (0, 0))
        self.assertEqual(state.acted_at, (-1, -1))
        opposite = TurnTree(replace(o, button=1), Profile(1), ranges={1: parse_range("KcKd")})
        self.assertEqual(opposite.river_state(opposite.root).actor, 0)

    def test_all_in_call_refund_and_fold(self):
        o = fixture(facing=50, stack=30)
        seats = list(o.seats)
        seats[1] = replace(seats[1], stack=0, status="I")
        o = replace(o, seats=tuple(seats), call=30, minimum=0, maximum=0)
        tree = TurnTree(o, Profile(1), ranges={1: parse_range("QsQh")})
        result = tree.run()
        wins = sum(r.probability*r.share for r in result.runouts)
        # Hero can win 260 after paying 30; villain receives a 20 refund.
        self.assertAlmostEqual(dict(result.values)["Call"], wins*260-30)
        self.assertEqual(dict(result.values)["Fold"], 0)
        self.assertEqual(result.nodes, 0)

    def test_chance_transitions_and_payouts_against_game(self):
        game = Game()
        game.new_hand()
        for _ in range(3):
            game.act("F")
        game.act("C")
        game.act("C")
        game.act("F")
        while game.street != "T":
            game.act("K")
        game.act("K")
        o = Reader().read(render(game))
        hole = tuple(game.players[1].hole)
        tree = TurnTree(o, Profile(1), game.events, {1: parse_range("".join(hole))})
        rng = random.Random(12)
        for _ in range(20):
            copy, state, first = deepcopy(game), tree.root, True
            while state.pending:
                move = rng.choice(tree.moves(state, root=first))
                copy.act(move.code, move.target)
                state = tree.step(state, move)
                first = False
            if state.folded >= 0:
                self.assertAlmostEqual(tree.terminal(state, (1.,)), copy.players[0].stack-game.players[0].stack)
                continue
            card = copy.board[-1]
            from pokato.analysis.river import RiverTree
            river = RiverTree.continuation(tree, card)
            state = tree.river_state(state)
            while state.pending:
                self.assertEqual(copy.actor, (0, 1)[state.actor])
                self.assertEqual(tuple(copy.players[i].bet for i in (0, 1)), state.bets)
                self.assertEqual(tuple(copy.players[i].stack for i in (0, 1)), state.stacks)
                move = rng.choice(river.moves(state))
                copy.act(move.code, move.target)
                state = river.step(state, move)
            self.assertEqual(copy.street, "X")
            self.assertAlmostEqual(river.terminal(state, (1.,)), copy.players[0].stack-game.players[0].stack)

    def test_bounded_search_and_inconsistent_history(self):
        with self.assertRaisesRegex(UnsupportedRiver, "budget"):
            TurnTree(fixture(), Profile(1), ranges={1: parse_range("QQ")}, node_budget=1).run()
        with self.assertRaisesRegex(UnsupportedRiver, "disagree"):
            TurnTree(fixture(facing=50), Profile(1), (Event(1, 1, "T", "R", 40),))


if __name__ == "__main__":
    unittest.main()
