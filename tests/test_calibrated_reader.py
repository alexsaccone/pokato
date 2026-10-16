from dataclasses import replace
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest
from PIL import Image, ImageDraw
from pokato.vision.calibrated import CalibratedReader, parse_amount
from pokato.vision.fixtures import SyntheticSkin, from_game, demo_frames
from pokato.vision.layouts import Layout
from pokato.vision.sources import Frame
from pokato.core.game import Game


class CalibratedTests(unittest.TestCase):
    def test_amount_units_thousands_decimal_and_mixed_bb_display(self):
        self.assertEqual(parse_amount("$1,200.50", ".01"), 120050)
        self.assertEqual(parse_amount("1.200,50€", ".01", ","), 120050)
        self.assertEqual(parse_amount("2.5K", "1"), 2500)
        self.assertEqual(parse_amount("12BB", ".01", multiplier="2"), 2400)
        for text in ("1,20.50", "1.2.3", "-5", "all-in", "NaN", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_amount(text, ".01")
        with self.assertRaises(ValueError):
            parse_amount("1.005", ".01")

    def test_two_independent_skins_generalize_to_unseen_amounts_and_sizes(self):
        for style in ("wide", "tall"):
            skin = SyntheticSkin(style)
            reader = CalibratedReader(skin.train())
            game = Game()
            game.new_hand()
            for _ in range(5):
                game.act("C")
            truth = from_game(game, 4)
            image = skin.render(truth)
            for scale in (1, 1.5, 2):
                size = tuple(round(v*scale) for v in image.size)
                result = reader.read(Frame(image.resize(size, Image.Resampling.NEAREST), 4, 1., style))
                with self.subTest(style=style, scale=scale):
                    self.assertFalse(result.issues, result.issues[:5])
                    self.assertEqual(result.snapshot.hole, truth.hole)
                    self.assertEqual(result.snapshot.board, truth.board)
                    self.assertEqual(result.snapshot.pot, truth.pot)
                    self.assertEqual([(s.stack, s.bet, s.status) for s in result.snapshot.seats],
                                     [(s.stack, s.bet, s.status) for s in truth.seats])
                    self.assertEqual(result.snapshot.actor, truth.actor)

    def test_profile_roundtrip_uncertainty_anchor_and_manual_provenance(self):
        skin = SyntheticSkin()
        layout = skin.train()
        game = Game()
        game.new_hand()
        truth = from_game(game, 0)
        image = skin.render(truth)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"profile.json"
            layout.save(path)
            reader = CalibratedReader(Layout.load(path))
        result = reader.read(Frame(image, 0, 0., "fixture"), {"pot": "$0.15"})
        self.assertIsNotNone(result.snapshot, result.issues)
        self.assertTrue(result.snapshot.manual)
        bad = image.copy()
        ImageDraw.Draw(bad).rectangle(skin.boxes["anchor"], fill="red")
        self.assertIsNone(reader.read(Frame(bad, 1, .25, "fixture")).snapshot)
        self.assertIsNone(reader.read(Frame(image.resize((800, 800)), 2, .5, "fixture")).snapshot)
        layout.examples.clear()
        self.assertIsNone(CalibratedReader(layout).read(Frame(image, 0, 0, "fixture")).snapshot)


if __name__ == "__main__":
    unittest.main()
