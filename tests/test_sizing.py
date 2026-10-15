from pathlib import Path
import tempfile
import unittest
from pokato.ui.sizing import Display, Preferences, font_pixels


class SizingTests(unittest.TestCase):
    def test_dense_laptop_uses_large_defaults_even_at_100_percent(self):
        self.assertEqual(Display(0, 0, 3840, 2160, 96).scale, 2.0)
        self.assertEqual(Display(0, 0, 3840, 2400, 240).scale, 2.5)
        self.assertGreaterEqual(font_pixels(10, 2.5), 40)
        self.assertGreaterEqual(font_pixels(8, 1), 14)

    def test_windows_fit_small_large_and_secondary_work_areas(self):
        for display in (Display(0, 0, 1366, 728), Display(0, 0, 1920, 1040),
                        Display(0, 0, 2560, 1400, 144), Display(0, 0, 3840, 2280, 240),
                        Display(-1920, 0, 1920, 1040), Display(0, -1080, 1920, 1040)):
            for rect in (display.table_rect(), display.hud_rect(), display.hud_rect(2.0)):
                with self.subTest(display=display, rect=rect):
                    w, h, x, y = rect
                    self.assertGreater(w, 0)
                    self.assertGreater(h, 0)
                    self.assertGreaterEqual(x, display.x)
                    self.assertGreaterEqual(y, display.y)
                    self.assertLessEqual(x + w, display.x + display.width)
                    self.assertLessEqual(y + h, display.y + display.height)

    def test_compact_4k_hud_is_a_little_over_one_sixteenth(self):
        for dpi in (96, 192, 240, 288):
            display = Display(0, 0, 3840, 2280, dpi)
            width, height, _, _ = display.hud_rect()
            ratio = width * height / (display.width * display.height)
            self.assertGreater(ratio, 1 / 16)
            self.assertLess(ratio, 0.075)
            self.assertGreaterEqual(font_pixels(10, display.compact_scale), 28)
            self.assertEqual(display.hud_rect(), display.hud_rect(2.0))

    def test_zoom_round_trip_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            preferences = Preferences(path)
            preferences.save(1.3)
            self.assertEqual(Preferences(path).zoom, 1.3)
            for invalid in ('{"hud_zoom": "large"}', '{"hud_zoom": 99}', '[]', 'broken'):
                path.write_text(invalid, encoding="utf-8")
                self.assertEqual(Preferences(path).zoom, 1)
