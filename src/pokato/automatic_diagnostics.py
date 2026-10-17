"""Exercise the actual Start button, desktop pixels and bundled offline models."""
from pathlib import Path
from dataclasses import replace
import json
import sys
import time
import traceback
import tkinter as tk
from unittest.mock import patch
from PIL import Image, ImageTk, ImageGrab
from pokato.ui.automatic_hud import AutomaticHUD
from pokato.ui.window import NativeWindow
from pokato.vision.capture import enable_dpi_awareness
from pokato.vision.sources import CaptureSource
from pokato.vision.automatic import AutomaticReader


def automatic_smoke(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    enable_dpi_awareness()
    root = tk.Tk()
    fixture = tk.Toplevel(root)
    fixture.overrideredirect(True)
    fixture.attributes('-topmost', True)
    assets = Path(__file__).parent/'assets'
    image = Image.open(assets/'automatic-smoke.png').convert('RGB')
    fixture.photo = ImageTk.PhotoImage(image)
    fixture_label = tk.Label(fixture, image=fixture.photo, borderwidth=0, highlightthickness=0)
    fixture_label.pack()
    fixture.geometry('1000x650+20+20')
    sources = []
    class SessionSource(CaptureSource):
        captured = False

        def next(self):
            frame = super().next()
            if frame is not None:
                self.captured = True
                return replace(frame, source=f'QA session {self.session}')

    def source_factory():
        source = SessionSource(bounds=(fixture.winfo_rootx(), fixture.winfo_rooty(),
                                       fixture.winfo_rootx()+1000, fixture.winfo_rooty()+650))
        source.session = len(sources)+1
        sources.append(source)
        return source
    class SmokeReader(AutomaticReader):
        partial = False
        count = 0

        def read(self, frame):
            reading = super().read(frame)
            if self.partial and len(reading.hand) == 2:
                # Emulate confidence rejection without changing the observed
                # glyphs; extraction itself is exercised by the offline corpus.
                hand = list(reading.hand)
                index = self.count % 2
                hand[index] = replace(hand[index], rank=None, suit=None, score=.4)
                self.count += 1
                reading = replace(reading, hand=tuple(hand), hand_views=(tuple(hand),))
            return reading

    reader = SmokeReader()
    hud = AutomaticHUD(root, reader=reader, source_factory=source_factory, settings_path=False)
    phase = 0
    partial_frames = set()
    started = time.monotonic()
    def show_fixture(name):
        fixture.photo = ImageTk.PhotoImage(Image.open(assets/name).convert('RGB'))
        fixture_label.configure(image=fixture.photo)
        root.update_idletasks()
    def finish(error=None):
        report['ok'] = error is None
        if error:
            report['error'] = error
        report['elapsed_seconds'] = round(time.monotonic()-started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        fixture.destroy()
        hud.close()
    def poll():
        nonlocal phase
        try:
            assert time.monotonic()-started < 90, 'Automatic HUD smoke timed out'
            if phase == 0:
                assert not hud.running and not sources
                assert hud.reader.ocr is None
                assert hud.start_button.cget('text') == 'Start analysis'
                report['checks'].append('HUD-only idle launch; no capture or model initialization before Start')
                hud.start_button.invoke()
                assert hud.running and len(sources) == 1
                phase = 1
            elif phase == 1 and sources[0].captured:
                assert hud.future is not None, 'Expected in-flight OCR'
                hud.start_button.invoke()
                assert not hud.running and sources[0].closed and hud.reading is None
                hud.start_button.invoke()
                assert hud.running and len(sources) == 2
                report['checks'].append('Stop and restart during in-flight OCR creates a new capture session')
                phase = 2
            elif phase == 2 and hud.reading is not None and hud.reading.hand_status == 'Hole cards confirmed':
                reading = hud.reading
                assert reading.source == 'QA session 2', 'Stale OCR result delivered after restart'
                assert tuple(c.value for c in reading.board) == ('Ac','7d','Ts','2h','9c'), reading
                assert tuple(c.value for c in reading.hand) == ('Kc','Kh'), reading
                assert reading.hero_verified
                assert any(p.value == '125.50' for p in reading.pots)
                report['checks'].append('One click captures real screen pixels and automatically reads unfamiliar cards, hero and pot')
                report['hud_excluded_from_capture'] = hud.excluded
                root.update_idletasks()
                ImageGrab.grab(window=NativeWindow(root).handle).save(report_path.with_suffix('.png'))
                reader.partial = True
                phase = 3
            elif phase == 3 and hud.reading is not None and hud.reading.hand_held:
                assert tuple(c.value for c in hud.reading.hand) == ('Kc', 'Kh'), hud.reading
                partial_frames.add(hud.reading.timestamp)
                if len(partial_frames) >= 2:
                    report['checks'].append('Alternating controlled OCR rejections keep both corroborated hole cards visible with held provenance')
                    root.update_idletasks()
                    ImageGrab.grab(window=NativeWindow(root).handle).save(report_path.with_name(report_path.stem+'-held.png'))
                    reader.partial = False
                    show_fixture('automatic-between-hands.png')
                    phase = 4
            elif phase == 4 and hud.reading is not None and not hud.reading.hand and not hud.reading.board:
                assert hud.hole_tracker.votes == [0, 0]
                report['checks'].append('Actual between-deal screen clears both old hole cards and their evidence')
                show_fixture('automatic-next-hand.png')
                phase = 5
            elif phase == 5 and hud.reading is not None and hud.reading.hand_status == 'Hole cards confirmed':
                assert tuple(c.value for c in hud.reading.hand) == ('Qd', 'Js'), hud.reading
                assert not hud.reading.board
                report['checks'].append('Actual next-deal pixels confirm the new pair without carrying either old card')
                hud.start_button.invoke()
                assert not hud.running and hud.reading is None and sources[1].closed
                assert hud.hole_tracker.votes == [0, 0]
                assert hud.pot.cget('text') == '' and hud.start_button.cget('text') == 'Start analysis'
                report['checks'].append('Stop immediately clears readings and closes capture')
                phase = 6
            elif phase == 6 and hud.future is None:
                hud.start_button.invoke()
                assert len(sources) == 3
                phase = 7
            elif phase == 7 and hud.reading is not None and hud.reading.hand_status == 'Hole cards confirmed':
                assert hud.reading.source == 'QA session 3'
                assert tuple(c.value for c in hud.reading.hand) == ('Qd', 'Js')
                report['checks'].append('Restart creates a fresh capture session; stale jobs are discarded')
                finish()
                return
            root.after(100, poll)
        except Exception:
            finish(traceback.format_exc())
    with patch('requests.sessions.Session.request', side_effect=AssertionError('No network access during inference')):
        root.after(600, poll)
        root.mainloop()
    return 0 if report['ok'] else 1
