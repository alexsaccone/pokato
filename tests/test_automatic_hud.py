import unittest
from unittest.mock import Mock, patch
from pokato.ui.automatic_hud import AutomaticHUD
from pokato.vision.automatic import AutomaticReader


class AutomaticHudTests(unittest.TestCase):
    def test_default_launch_does_not_construct_the_practice_application(self):
        from pokato.app import main
        with patch('pokato.app.tk.Tk') as root, patch('pokato.app.enable_dpi_awareness'), patch(
                'pokato.app.App') as practice, patch('pokato.ui.automatic_hud.AutomaticHUD') as hud:
            main([])
            hud.assert_called_once_with(root.return_value)
            practice.assert_not_called()
            root.return_value.mainloop.assert_called_once()

    def test_explicit_practice_launch_remains_available(self):
        from pokato.app import main
        with patch('pokato.app.tk.Tk'), patch('pokato.app.enable_dpi_awareness'), patch(
                'pokato.app.App') as practice, patch('pokato.ui.automatic_hud.AutomaticHUD') as hud:
            main(['--practice'])
            practice.assert_called_once()
            hud.assert_not_called()

    def test_capture_end_does_not_run_the_recognizer_on_a_missing_frame(self):
        source, reader = Mock(), Mock()
        source.next.return_value = None
        self.assertIsNone(AutomaticHUD.analyze(source, reader))
        reader.read.assert_not_called()

    def test_creating_the_reader_does_not_initialize_models(self):
        with patch('pokato.vision.ocr.LocalOCR') as engine:
            reader = AutomaticReader()
            self.assertIsNone(reader.ocr)
            engine.assert_not_called()
