import unittest
from PIL import Image, ImageDraw
from pokato.core.game import Game
from pokato.core.cards import DECK, SUIT_SYMBOLS
from pokato.simulator.bots import choose_action
from pokato.simulator.render import render
from pokato.simulator.layout import FIELDS, CELL_W, CELL_H, glyph
from pokato.vision.reader import Reader, ReadError
from pokato.vision.tracker import Tracker


class VisionTests(unittest.TestCase):
    def test_all_card_symbols_are_visible_and_read_at_compact_sizes(self):
        game, reader = Game(), Reader()
        game.new_hand()
        while game.street != "R":
            game.act("K" if game.legal()["check"] else "C")
        for start in range(0, len(DECK), 7):
            cards = tuple(DECK[(start+i) % len(DECK)] for i in range(7))
            game.players[0].hole, game.board = list(cards[:2]), list(cards[2:])
            frame = render(game)
            field = FIELDS["hole0"]
            suit_pixels = frame.crop((field.x+CELL_W, field.y, field.x+2*CELL_W, field.y+CELL_H))
            self.assertEqual(suit_pixels.tobytes(), glyph(SUIT_SYMBOLS[cards[0][1]]).tobytes())
            for size in ((490, 400), (637, 520), (980, 800)):
                with self.subTest(cards=cards, size=size):
                    observed = reader.read(frame.resize(size, Image.Resampling.NEAREST))
                    self.assertEqual(observed.hole, cards[:2])
                    self.assertEqual(observed.board, cards[2:])

    def test_reconstruct_complete_hand_from_pixels(self):
        g, reader, tracker = Game(), Reader(), Tracker()
        g.new_hand()
        while True:
            o = reader.read(render(g))
            tracker.accept(o)
            self.assertEqual(o.hole, tuple(g.players[0].hole))
            self.assertEqual(o.board, tuple(g.board))
            self.assertEqual(o.pot, g.pot)
            self.assertEqual(o.events, tuple(g.events[-8:]))
            if g.actor < 0:
                break
            g.act(*choose_action(g))
        self.assertEqual(tracker.events, g.events)

    def test_occlusion_and_scaling_fail_closed(self):
        g, reader = Game(), Reader()
        g.new_hand()
        frame = render(g)
        ImageDraw.Draw(frame).rectangle(FIELDS["pot"].box, fill="red")
        with self.assertRaises(ReadError):
            reader.read(frame)
        with self.assertRaises(ReadError):
            reader.read(render(g).resize((490, 345)))

    def test_resized_table_preserves_observation(self):
        g, reader = Game(), Reader()
        g.new_hand()
        frame = render(g)
        expected = reader.read(frame)
        for size in ((490, 400), (588, 480), (637, 520), (784, 640), (823, 672),
                     (981, 801), (1127, 920), (1470, 1200), (1960, 1600)):
            with self.subTest(size=size):
                observed = reader.read(frame.resize(size, Image.Resampling.NEAREST))
                self.assertEqual(observed.hole, expected.hole)
                self.assertEqual(observed.seats, expected.seats)
                self.assertEqual(observed.events, expected.events)
                self.assertEqual(observed.pot, expected.pot)

    def test_missed_actions_require_new_hand(self):
        g, reader, tracker = Game(), Reader(), Tracker()
        g.new_hand()
        for _ in range(12):
            if g.actor < 0:
                break
            g.act("K" if g.legal()["check"] else "C")
        with self.assertRaisesRegex(ReadError, "Missed action"):
            tracker.accept(reader.read(render(g)))

    def test_compact_reading_through_multiple_hands(self):
        reader = Reader()
        for seed in range(5):
            g = Game(seed)
            g.new_hand()
            while True:
                for size in ((490, 400), (637, 520)):
                    observed = reader.read(render(g).resize(size, Image.Resampling.NEAREST))
                    self.assertEqual(observed.hole, tuple(g.players[0].hole))
                    self.assertEqual(observed.board, tuple(g.board))
                    self.assertEqual(observed.events, tuple(g.events[-8:]))
                if g.actor < 0:
                    break
                g.act("K" if g.legal()["check"] else "C")


if __name__ == "__main__":
    unittest.main()
