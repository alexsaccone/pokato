from dataclasses import replace
import unittest
from pokato.vision.calibrated import CalibratedReader, TableReading
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


if __name__ == "__main__":
    unittest.main()
