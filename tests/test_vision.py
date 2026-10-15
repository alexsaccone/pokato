import unittest
from PIL import ImageDraw
from pokato.core.game import Game
from pokato.simulator.bots import choose_action
from pokato.simulator.render import render
from pokato.simulator.layout import FIELDS
from pokato.vision.reader import Reader, ReadError
from pokato.vision.tracker import Tracker


class VisionTests(unittest.TestCase):
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

    def test_missed_actions_require_new_hand(self):
        g, reader, tracker = Game(), Reader(), Tracker()
        g.new_hand()
        for _ in range(12):
            if g.actor < 0:
                break
            g.act("K" if g.legal()["check"] else "C")
        with self.assertRaisesRegex(ReadError, "Missed action"):
            tracker.accept(reader.read(render(g)))


if __name__ == "__main__":
    unittest.main()
