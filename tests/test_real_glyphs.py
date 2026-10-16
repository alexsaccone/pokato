"""Minimal HD Poker pixel crops; no names, wallet, chat or full screenshots."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from pokato.vision.layouts import Layout, Region
from pokato.vision.calibrated import CalibratedReader, parse_amount


class RealGlyphTests(unittest.TestCase):
    folder = Path(__file__).parent/'fixtures'/'hd_poker'

    def test_real_fonts_gradients_touching_amounts_and_unseen_strings(self):
        rows = json.loads((self.folder/'labels.json').read_text())
        layout = Layout()
        for row in rows:
            if row['split'] == 'train':
                region = Region('pot', (0, 0, 1, 1), row['kind'], row['group'], foreground=row['foreground'])
                with Image.open(self.folder/row['file']) as image:
                    CalibratedReader.teach(layout, region, image, row['label'])
        self.assertTrue(any(e.kind == 'number_text' for e in layout.examples))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'profile.json'
            layout.save(path)
            layout = Layout.load(path)
        reader = CalibratedReader(layout)
        accepted = 0
        for row in rows:
            region = Region('pot', (0, 0, 1, 1), row['kind'], row['group'], foreground=row['foreground'])
            with Image.open(self.folder/row['file']) as image:
                field = reader.field(region, image)
            expected = parse_amount(row['label']) if row['kind'] == 'number' and row['label'] is not None else row['label']
            with self.subTest(file=row['file'], split=row['split']):
                if field.value is None:
                    self.assertTrue(field.issue)
                    self.assertEqual(row['split'], 'test')
                else:
                    self.assertEqual(field.value, expected, field)
                    self.assertEqual(field.approximate, row['kind'] == 'number' and row['label'].endswith('K'))
                    if row['split'] == 'test':
                        accepted += 1
        self.assertGreaterEqual(accepted, 8)

    def test_missing_or_clipped_card_ink_is_unknown_and_bad_zero_teaching_is_rejected(self):
        region = Region('hole0.rank', (0, 0, 1, 1), 'rank', foreground='card')
        layout = Layout()
        blank_card = Image.new('RGB', (60, 70), '#eeeeee')
        with self.assertRaisesRegex(ValueError, 'missing or clipped'):
            CalibratedReader.teach(layout, region, blank_card, 'K')
        CalibratedReader.teach(layout, region, Image.new('RGB', (60, 70), '#b82622'), 'empty')
        field = CalibratedReader(layout).field(region, blank_card)
        self.assertIsNone(field.value)
        self.assertIn('missing or clipped', field.issue)
        row = json.loads((self.folder/'labels.json').read_text())[0]
        amount = Region('pot', (0, 0, 1, 1), 'number', foreground='light')
        with Image.open(self.folder/row['file']) as image:
            CalibratedReader.teach(layout, amount, image, row['label'])
            with self.assertRaisesRegex(ValueError, 'nonzero'):
                CalibratedReader.teach(layout, amount, image, '=0')

    def test_foreground_settings_validate_and_do_not_mix_template_groups(self):
        with self.assertRaises(ValueError):
            Region('pot', (0, 0, 1, 1), 'number', foreground='unknown')
        region = Region('pot', (0, 0, 1, 1), 'number', foreground='light')
        layout = Layout()
        with Image.open(self.folder/'train-00.png') as image:
            CalibratedReader.teach(layout, region, image, '237.5K')
            self.assertIsNone(CalibratedReader(layout).field(replace(region, foreground='auto'), image).value)

    def test_touching_amount_examples_work_with_the_default_template_group(self):
        layout = Layout()
        region = Region('pot', (0, 0, 1, 1), 'number', foreground='light')
        with Image.open(self.folder/'train-07.png') as image:
            example = CalibratedReader.teach(layout, region, image, '500')
            self.assertEqual(example.kind, 'number_text')
            self.assertEqual(CalibratedReader(layout).field(region, image).value, 500)

    def test_colored_timer_marker_survives_green_yellow_and_red_phases(self):
        layout = Layout()
        region = Region('seat0.actor', (0, 0, 1, 1), 'flag', foreground='color')
        CalibratedReader.teach(layout, region, Image.new('RGB', (20, 16), '#52ce00'), 'yes')
        CalibratedReader.teach(layout, region, Image.new('RGB', (20, 16), '#eeeeee'), 'no')
        reader = CalibratedReader(layout)
        for color in ('#52ce00', '#d0a300', '#d04422'):
            self.assertIs(reader.field(region, Image.new('RGB', (20, 16), color)).value, True)
        self.assertIs(reader.field(region, Image.new('RGB', (20, 16), '#eeeeee')).value, False)
