from dataclasses import replace
import unittest
from pokato.vision.calibrated import CalibratedReader, TableReading, TableSnapshot, TableSeat
from pokato.vision.layouts import Layout
from pokato.vision.fixtures import SyntheticSkin, from_game
from pokato.vision.sources import Frame
from pokato.vision.table_history import TableHistory
from pokato.core.game import Game


def reading(snapshot):
    return TableReading(None, (), snapshot, ())


class TableHistoryTests(unittest.TestCase):
    def test_visible_ledger_matches_real_game_without_using_the_event_tape(self):
        skin = SyntheticSkin()
        layout = skin.train()
        reader, history = CalibratedReader(layout), TableHistory(layout, 1)
        game = Game()
        game.new_hand()
        index = 0
        while game.street != "X":
            snapshot = from_game(game, index)
            result = history.accept(reader.read(Frame(skin.render(snapshot), index, index*.25, "fixture")))
            self.assertEqual(result.quality, "reconciled", result.message)
            self.assertEqual(result.events, tuple(game.events))
            self.assertEqual([s.invested for s in result.observation.seats], [p.invested for p in game.players])
            index += 1
            game.act("F" if game.street == "P" and game.actor in (3, 4, 5) else "K" if game.legal()["check"] else "C")

    def test_debounce_missing_actions_manual_edits_and_new_hand_resync(self):
        layout = SyntheticSkin().layout
        history = TableHistory(layout, 2)
        game = Game()
        game.new_hand()
        initial = from_game(game, 0)
        self.assertEqual(history.accept(reading(initial)).quality, "waiting")
        self.assertEqual(history.accept(reading(initial)).quality, "waiting")
        self.assertEqual(history.accept(reading(replace(initial, index=1, timestamp=.25))).quality, "reconciled")
        game.act("C")
        game.act("C")
        snapshot = from_game(game, 2)
        history.accept(reading(snapshot))
        result = history.accept(reading(replace(snapshot, index=3, timestamp=.75)))
        self.assertEqual(result.quality, "gap")
        game.act("C")
        snapshot = from_game(game, 4)
        history.accept(reading(snapshot))
        self.assertEqual(history.accept(reading(replace(snapshot, index=5))).quality, "gap")
        while game.street != "X":
            game.act("F")
        game.new_hand()
        snapshot = from_game(game, 6)
        history.accept(reading(snapshot))
        self.assertEqual(history.accept(reading(replace(snapshot, index=7))).quality, "reconciled")
        self.assertEqual(history.accept(reading(replace(snapshot, manual=True))).quality, "gap")

    def test_midhand_start_and_identity_replacement_never_inherit_history(self):
        layout = SyntheticSkin().layout
        history = TableHistory(layout, 1)
        game = Game()
        game.new_hand()
        initial = from_game(game, 0)
        history.accept(reading(initial))
        seats = tuple(replace(s, identity="old") for s in initial.seats)
        history.previous = replace(initial, seats=seats)
        changed = list(seats)
        changed[2] = replace(changed[2], identity="new")
        self.assertEqual(history.accept(reading(replace(initial, index=1, seats=tuple(changed)))).quality, "gap")
        game.act("C")
        fresh = TableHistory(layout, 1)
        self.assertEqual(fresh.accept(reading(from_game(game, 1))).quality, "unverified")

    def test_raise_prices_and_short_all_in_rights_match_visible_game_ledger(self):
        for stacks in ([1000]*6, [1000, 70, 50, 25, 30, 40]):
            history = TableHistory(SyntheticSkin().layout, 1)
            game = Game(stacks=stacks)
            game.new_hand()
            index = 0
            while game.street != "X":
                result = history.accept(reading(from_game(game, index)))
                self.assertEqual(result.quality, "reconciled", result.message)
                self.assertEqual(result.events, tuple(game.events))
                legal = game.legal()
                self.assertEqual((result.observation.call, result.observation.minimum, result.observation.maximum),
                                 (legal["call"], legal["min_raise"], legal["max_raise"]))
                if legal["min_raise"] and index in (0, 1, 2, 3, 7, 11):
                    game.act("R", legal["min_raise"])
                else:
                    game.act("K" if legal["check"] else "C")
                index += 1
                self.assertLess(index, 60)

    def test_heads_up_positions_and_unreadable_frames_reset_live_stabilization(self):
        layout = Layout(seat_count=2)
        history = TableHistory(layout, 2)
        start = TableSnapshot(0, 0, ("As", "Kd"), (), 15,
                              (TableSeat("A", 995, 5), TableSeat("A", 990, 10)), 0, 0, "P", 1.)
        self.assertEqual(history.accept(reading(start)).quality, "waiting")
        bad = TableReading(None, (), None, ("Unreadable pot",))
        self.assertEqual(history.accept(bad).quality, "unreadable")
        self.assertEqual(history.accept(reading(replace(start, index=1))).quality, "waiting")
        self.assertEqual(history.accept(reading(replace(start, index=2))).quality, "reconciled")
        self.assertIsNone(history.result(start).observation)  # Legacy export is six-seat only.
        history.required = 1
        call = replace(start, index=3, pot=20, actor=1, seats=(TableSeat("A", 990, 10), start.seats[1]))
        self.assertEqual(history.accept(reading(call)).quality, "reconciled")
        flop = replace(call, index=4, actor=1, street="F", board=("2c", "3h", "7d"),
                       seats=(TableSeat("A", 990, 0), TableSeat("A", 990, 0)))
        result = history.accept(reading(flop))
        self.assertEqual(result.quality, "reconciled", result.message)
        self.assertEqual(result.events[-1].action, "K")


if __name__ == "__main__":
    unittest.main()
