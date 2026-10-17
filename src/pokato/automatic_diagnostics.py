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


def automatic_smoke(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    enable_dpi_awareness()
    root = tk.Tk()
    fixture = tk.Toplevel(root)
    fixture.overrideredirect(True)
    fixture.attributes('-topmost', True)
    image = Image.open(Path(__file__).parent/'assets'/'automatic-smoke.png').convert('RGB')
    fixture.photo = ImageTk.PhotoImage(image)
    tk.Label(fixture, image=fixture.photo, borderwidth=0, highlightthickness=0).pack()
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
    hud = AutomaticHUD(root, source_factory=source_factory, settings_path=False)
    phase = 0
    started = time.monotonic()
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
            assert time.monotonic()-started < 50, 'Automatic HUD smoke timed out'
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
            elif phase == 2 and hud.reading is not None and hud.reading.table_found:
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
                hud.start_button.invoke()
                assert not hud.running and hud.reading is None and sources[1].closed
                assert hud.pot.cget('text') == '' and hud.start_button.cget('text') == 'Start analysis'
                report['checks'].append('Stop immediately clears readings and closes capture')
                phase = 3
            elif phase == 3 and hud.future is None:
                hud.start_button.invoke()
                assert len(sources) == 3
                phase = 4
            elif phase == 4 and hud.reading is not None and hud.reading.table_found:
                assert hud.reading.source == 'QA session 3'
                assert tuple(c.value for c in hud.reading.board) == ('Ac','7d','Ts','2h','9c')
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
