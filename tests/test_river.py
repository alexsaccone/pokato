from copy import deepcopy
from dataclasses import replace
import random
import unittest
from pokato.analysis.bayes import Posterior, SessionModel, ResponseCount
from pokato.analysis.history import Profile
from pokato.analysis.ranges import parse_range, combo_key
from pokato.analysis.river import RiverTree, UnsupportedRiver
from pokato.analysis.coach import analyze
from pokato.core.game import Game, Event
from pokato.vision.reader import Observation, Seat, Reader
from pokato.simulator.render import render


class PassiveModel:
    def posterior(self, street, owed, pot):
        return Posterior(("F", "C", "R"), (0., 24., 0.), 0, 0) if owed else Posterior(("K", "R"), (24., 0.), 0, 0)


def fixture(hero=("Ks", "Kh"), facing=0, stack=300):
    seats = (Seat("A", stack, 0, 100), Seat("A", stack-facing, facing, 100+facing),
             *(Seat("F", 1000, 0, 0) for _ in range(4)))
    return Observation(1, "R", 0, 0, 200+facing, facing, 2*facing if facing else 10,
                       stack, hero, tuple("Ac 2d 3h 7s 9c".split()), seats, (), 1.)


class RiverTests(unittest.TestCase):
    def test_belief_policy_does_not_choose_with_hidden_cards(self):
        o = fixture()
        tree = RiverTree(o, Profile(1), ranges={1: parse_range("AsAh, QsQh")}, model=PassiveModel())
        result = tree.run()
        # Half nuts, half a worse pair. Clairvoyant bet-only-when-winning
        # would score 250; every public-belief action instead scores 100.
        for label, ev in result.values:
            self.assertAlmostEqual(ev, 100, msg=label)

    def test_check_closes_after_villain_check_and_call_closes_bet(self):
        o = fixture()
        result = RiverTree(o, Profile(1), (Event(1, 1, "R", "K", 0),),
                           {1: parse_range("AsAh, QsQh")}).run()
        self.assertFalse(any(b.action == "Check" for b in result.branches))
        facing = fixture(facing=50)
        result = RiverTree(facing, Profile(1), (Event(1, 1, "R", "R", 50),),
                           {1: parse_range("QsQh")}).run()
        self.assertAlmostEqual(dict(result.values)["Call"], 250)
        self.assertEqual(dict(result.values)["Fold"], 0)
        self.assertFalse(any(b.action == "Call" for b in result.branches))

    def test_branch_mass_legality_and_raise_cap(self):
        tree = RiverTree(fixture(), Profile(1), ranges={1: parse_range("AsAh, QsQh")})
        result = tree.run()
        self.assertGreater(len(result.values), 3)
        for action in {b.action for b in result.branches}:
            self.assertAlmostEqual(sum(b.probability for b in result.branches if b.action == action), 1)
        self.assertTrue(any(b.response.startswith("Raise") for b in result.branches))
        self.assertLess(result.nodes, 5000)
        capped = replace(tree.root, aggression=3)
        self.assertFalse(any(m.code == "R" for m in tree.moves(capped)))

    def test_transitions_and_dealt_payouts_against_game_engine(self):
        game = Game()
        game.new_hand()
        for _ in range(3):
            game.act("F")
        game.act("C")
        game.act("C")
        game.act("F")
        while game.street != "R":
            game.act("K")
        game.act("K")  # opponent checks to hero
        o = Reader().read(render(game))
        hidden = game.players[1].hole
        tree = RiverTree(o, Profile(1), game.events, {1: parse_range("".join(hidden))})
        rng = random.Random(9)
        for _ in range(40):
            copy, state, first = deepcopy(game), tree.root, True
            while state.pending:
                moves = tree.moves(state, root=first)
                move = rng.choice(moves)
                self.assertEqual(copy.actor, state.actor)
                copy.act(move.code, move.target)
                state = tree.step(state, move)
                first = False
                if state.pending:
                    self.assertEqual(tuple(copy.players[i].stack for i in (0, 1)), state.stacks)
                    self.assertEqual(tuple(copy.players[i].bet for i in (0, 1)), state.bets)
            self.assertEqual(copy.street, "X")
            self.assertAlmostEqual(tree.terminal(state, (1.,)), copy.players[0].stack - game.players[0].stack)

    def test_search_budget_and_corrected_state_fallback(self):
        with self.assertRaisesRegex(UnsupportedRiver, "budget"):
            RiverTree(fixture(), Profile(1), ranges={1: parse_range("QQ")}, node_budget=1).run()
        o = fixture(facing=50)
        bad_events = (Event(1, 1, "R", "R", 40),)
        advice = analyze(o, [Profile(i) for i in range(6)], bad_events, samples=50,
                         ranges={1: parse_range("QsQh")})
        self.assertEqual(advice.engine, "scenario")
        self.assertIn("disagree", advice.assumptions)

    def test_session_evidence_changes_tree_ev(self):
        o = fixture()
        profiles = [Profile(i) for i in range(6)]
        ranges = {1: parse_range("AsAh, QsQh")}
        base = analyze(o, profiles, ranges=ranges)
        models = (SessionModel(1, (ResponseCount("R", "small", "F", 100),)),)
        adapted = analyze(o, profiles, ranges=ranges, models=models)
        self.assertEqual(adapted.engine, "river-tree")
        first = {a.label: a.ev for a in base.actions}
        second = {a.label: a.ev for a in adapted.actions}
        self.assertGreater(abs(first["Bet 67"] - second["Bet 67"]), 1)
        self.assertTrue(any("100 direct" in line for line in adapted.evidence))

    def test_past_aggression_changes_current_betting_range_and_call_ev(self):
        o = fixture(facing=50)
        events = (Event(1, 1, "R", "R", 50),)
        aggressive = SessionModel(1, (ResponseCount("R", "open", "R", 100),))
        passive = SessionModel(1, (ResponseCount("R", "open", "K", 100),))
        profiles = [Profile(i) for i in range(6)]
        a = analyze(o, profiles, events, models=(aggressive,))
        p = analyze(o, profiles, events, models=(passive,))
        self.assertGreater(a.equity.share, p.equity.share)
        self.assertGreater(next(v.ev for v in a.actions if v.label == "Call"),
                           next(v.ev for v in p.actions if v.label == "Call"))

    def test_short_all_in_call_and_corrected_bounds(self):
        o = fixture(facing=50, stack=30)
        o = replace(o, call=30, minimum=0, maximum=0)
        seats = list(o.seats)
        seats[1] = replace(seats[1], stack=0, status="I")
        o = replace(o, seats=tuple(seats))
        result = RiverTree(o, Profile(1), ranges={1: parse_range("QsQh")}).run()
        self.assertEqual({a for a, ev in result.values}, {"Fold", "Call"})
        self.assertAlmostEqual(dict(result.values)["Call"], 230)
        corrected = replace(fixture(), minimum=0, maximum=0)
        with self.assertRaisesRegex(UnsupportedRiver, "bounds"):
            RiverTree(corrected, Profile(1))
