from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
from pokato.analysis.history import History, Profile
from pokato.analysis.equity import equity, range_weight
from pokato.analysis.coach import analyze
from pokato.core.game import Game, Event
from pokato.simulator.render import render
from pokato.vision.reader import Reader


class AnalysisTests(unittest.TestCase):
    def test_exact_river_tie_and_nuts(self):
        tie = equity(("2c", "3d"), tuple("As Ks Qs Js Ts".split()), [Profile(1)])
        self.assertEqual(tie.share, 0.5)
        self.assertTrue(tie.exact)
        nuts = equity(("As", "Ks"), tuple("Qs Js Ts 2c 3d".split()), [Profile(1)])
        self.assertEqual(nuts.share, 1.0)

    def test_history_persists_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            history = History(path)
            events = [Event(1, 1, "P", "B", 5), Event(2, 2, "P", "B", 10),
                      Event(3, 3, "P", "C", 10), Event(4, 4, "P", "R", 30), Event(5, 3, "P", "F", 0)]
            history.record("session", 1, events)
            history.record("session", 1, events)
            self.assertEqual(history.profile(3), Profile(3, 1, 1, 0, 2, 1))
            history.close()
            history = History(path)
            self.assertEqual(history.profile(3).hands, 1)
            history.close()

    def test_raise_observation_changes_range_weight(self):
        profile = Profile(1)
        event = [Event(3, 1, "P", "R", 30)]
        premium = range_weight(("As", "Ah"), (), event, profile)
        weak = range_weight(("2s", "7h"), (), event, profile)
        self.assertGreater(premium, weak)

    def test_call_ev_formula_and_side_pot_abstention(self):
        game = Game()
        game.new_hand()
        o = Reader().read(render(game))
        seats = list(o.seats)
        for i, s in enumerate(seats):
            seats[i] = replace(s, status="A" if i < 2 else "F", bet=0, invested=0)
        seats[1] = replace(seats[1], bet=50, invested=150)
        o = replace(o, actor=0, street="R", hole=("2c", "3d"),
                    board=tuple("As Ks Qs Js Ts".split()), seats=tuple(seats), pot=150,
                    call=50, minimum=0, maximum=0)
        advice = analyze(o, [Profile(i) for i in range(6)], samples=40)
        call = next(a for a in advice.actions if a.label == "Call")
        self.assertEqual(advice.threshold, 0.25)
        self.assertEqual(call.ev, 50)
        seats[1] = replace(seats[1], status="I", stack=0)
        self.assertFalse(analyze(replace(o, seats=tuple(seats)), [Profile(i) for i in range(6)]).actions)


if __name__ == "__main__":
    unittest.main()
