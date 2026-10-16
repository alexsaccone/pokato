"""Exercise the reader's actual Tk windows, local inputs and frozen codec bundle."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
import traceback
from PIL import Image, ImageDraw, ImageGrab, ImageTk
from .app import App
from .ui.table_reader import DemoSource
from .ui.window import NativeWindow
from .ui.sizing import geometry
from .vision.capture import enable_dpi_awareness
from .vision.calibrated import CalibratedReader
from .vision.fixtures import demo_frames
from .vision.sources import ImageSource, VideoSource, CaptureSource, Frame


class SlowSource(DemoSource):
    def next(self):
        time.sleep(.25)
        return super().next()


def reader_smoke(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    folder = report_path.parent / "reader-fixtures"
    folder.mkdir(exist_ok=True)
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": []}
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root, samples=100, database=":memory:", settings_path=False)
    app.paused = True
    studio = None
    fixture = None
    started = time.monotonic()
    phase = "open"
    resume_after = started+.3
    first_layout, frames = demo_frames()
    first_image = frames[0][0]
    first_image.save(folder / "first.png")
    first_layout.save(folder / "layout.json")

    def finish(error=None):
        report["ok"] = error is None
        if error:
            report["error"] = error
        report["elapsed_seconds"] = round(time.monotonic()-started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.close()

    root.report_callback_exception = lambda kind, value, tb: finish("".join(traceback.format_exception(kind, value, tb)))

    def tick():
        nonlocal phase, studio, fixture, resume_after
        try:
            if time.monotonic()-started > 60:
                raise TimeoutError(f"Reader smoke timed out in {phase}: {studio.status.get() if studio else ''}")
            if time.monotonic() < resume_after:
                root.after(80, tick)
                return
            if phase == "open":
                studio = app.open_table_reader()
                assert app.paused and not app.root.winfo_viewable() and not app.hud.winfo_viewable()
                studio.load_layout(folder / "layout.json")
                studio.replace_source(ImageSource([folder / "first.png"]))
                phase = "image"
            elif studio.future is not None or studio.pending_read:
                pass
            elif phase == "image":
                assert studio.reading and studio.reading.snapshot, studio.status.get()
                assert studio.reading.snapshot.hole == frames[0][1].hole
                assert studio.result.quality == "reconciled", studio.result
                assert len(studio.fields.get_children()) == len(first_layout.regions)
                report["checks"].append("image input, saved calibration, field inspector and blind-only synchronization")
                studio.field.set("hole0.rank")
                studio.select_field()
                studio.selected_box = studio.layout.regions["hole0.rank"].box
                studio.set_region()
                phase = "region"
            elif phase == "region":
                studio.example_label.set(frames[0][1].hole[0][0])
                before = len(studio.layout.examples)
                studio.teach()
                assert len(studio.layout.examples) == before+1
                studio.save_layout(folder / "edited-layout.json")
                report["checks"].append("ROI editor, teach example, crop preview and portable profile save")
                phase = "taught"
            elif phase == "taught":
                assert studio.reading.snapshot
                studio.overrides["pot"] = "$0.15"
                studio.request_read(reuse=True)
                phase = "manual"
            elif phase == "manual":
                assert studio.reading.snapshot.manual
                assert studio.result.quality == "gap"
                assert studio.result.observation is None
                assert "withheld" in studio.hud_quality.cget("text")
                report["checks"].append("manual provenance prevents trusted action history and external recommendations")
                studio.replace_source(DemoSource(frames))
                phase = "sequence"
            elif phase == "sequence":
                assert studio.result.quality == "reconciled", studio.status.get()
                if studio.frame.index < 3:
                    studio.next_frame()
                else:
                    assert len(studio.result.events) == 5
                    studio.export(folder / "readings.json")
                    exported = json.loads((folder / "readings.json").read_text(encoding="utf-8"))
                    assert not exported["recommendations_enabled"]
                    assert exported["readings"][-1]["history"]["observation"]
                    report["checks"].append("frame sequence, inferred actions, chip ledger and normalized observation export")
                    bad = first_image.copy()
                    ImageDraw.Draw(bad).rectangle((20, 16, 220, 55), fill="red")
                    studio.deliver(CalibratedReader(studio.layout).read(Frame(bad, 4, 1., "bad anchor")))
                    assert studio.reading.snapshot is None and not studio.hud_cards.cget("text")
                    report["checks"].append("bad anchor withholds state and clears floating HUD cards")
                    # Decode a local lossless recording through the same OpenCV
                    # import used by the frozen executable, without downloaded media.
                    import cv2
                    import numpy as np
                    video = folder / "fixture.avi"
                    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"FFV1"), 4, first_image.size)
                    assert writer.isOpened(), "FFV1 fixture encoder unavailable"
                    for image, _ in frames[:3]:
                        writer.write(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
                    writer.release()
                    studio.replace_source(VideoSource(video))
                    phase = "video"
            elif phase == "video":
                assert studio.reading.snapshot and studio.result.quality == "reconciled", studio.status.get()
                report["checks"].append("bundled OpenCV/FFmpeg video decoding and calibrated recognition")
                studio.replace_source(SlowSource(frames))
                studio.request_read()
                studio.layout, tall_frames = demo_frames("tall")
                studio.replace_source(DemoSource(tall_frames))
                studio.refresh_profile()
                phase = "tall"
            elif phase == "tall":
                assert studio.reading.snapshot and studio.result.quality == "reconciled", studio.status.get()
                assert studio.frame.image.size == (1000, 900)
                assert len(studio.records) == 1
                report["checks"].append("switching sources during a slow read discards the old result")
                report["checks"].append("second layout, different aspect ratio, font and table styling")
                studio.layout = first_layout
                studio.refresh_profile()
                fixture = tk.Toplevel(root)
                fixture.title("Pokato reader QA fixture")
                fixture.overrideredirect(True)
                fixture.attributes("-topmost", True)
                fixture.geometry("1200x760+20+20")
                fixture.photo = ImageTk.PhotoImage(first_image)
                label = tk.Label(fixture, image=fixture.photo, borderwidth=0, highlightthickness=0)
                label.pack()
                fixture.deiconify()
                fixture.lift()
                fixture.update_idletasks()
                NativeWindow(fixture).api.ShowWindow(NativeWindow(fixture).handle, 9)
                fixture.geometry("1200x760+20+20")
                resume_after = time.monotonic()+.6
                phase = "capture-start"
            elif phase == "capture-start":
                studio.replace_source(CaptureSource(window=NativeWindow(fixture).handle))
                phase = "capture-first"
            elif phase == "capture-first":
                assert studio.reading.snapshot, studio.status.get()
                assert studio.result.quality == "waiting"
                studio.next_frame()
                phase = "capture-second"
            elif phase == "capture-second":
                assert studio.result.quality == "reconciled", studio.status.get()
                report["checks"].append("actual selected-window pixel capture and two-frame live stabilization")
                x, y = fixture.winfo_rootx(), fixture.winfo_rooty()
                screen = CaptureSource(bounds=(x, y, x+1200, y+760))
                screen_reading = CalibratedReader(first_layout).read(screen.next())
                screen.close()
                assert screen_reading.snapshot and screen_reading.snapshot.hole == frames[0][1].hole, screen_reading.issues
                report["checks"].append("explicit screen-region capture of the separate QA table")
                fixture.destroy()
                fixture = None
                studio.next_frame()
                phase = "closed-input"
            elif phase == "closed-input":
                assert studio.reading is None and not studio.hud_cards.cget("text")
                assert "closed" in studio.status.get()
                report["checks"].append("closed input clears stale readings and HUD")
                studio.open_demo()
                phase = "hud"
            elif phase == "hud":
                assert studio.reading.snapshot
                studio.hud.withdraw()
                studio.window.geometry(geometry(studio.display.fit(1320*studio.scale, 880*studio.scale)))
                studio.window.lift()
                resume_after = time.monotonic()+.5
                phase = "studio-screenshot"
            elif phase == "studio-screenshot":
                assert studio.window.winfo_viewable()
                ImageGrab.grab(window=NativeWindow(studio.window).handle).save(report_path.with_suffix(".png"))
                studio.show_hud()
                studio.hud.geometry(geometry(studio.hud_display.hud_rect()))
                studio.hud.lift()
                resume_after = time.monotonic()+.5
                phase = "screenshot"
            elif phase == "screenshot":
                assert studio.window.winfo_viewable() and studio.hud.winfo_viewable()
                ImageGrab.grab(window=NativeWindow(studio.hud).handle).save(report_path.with_name(report_path.stem+"-hud.png"))
                assert "♠" in studio.hud_cards.cget("text") or any(symbol in studio.hud_cards.cget("text") for symbol in "♣♦♥")
                studio.close()
                assert app.paused
                resume_after = time.monotonic()+.5
                phase = "restore"
            elif phase == "restore":
                assert app.root.winfo_viewable()
                report["checks"].append("floating suit-symbol HUD, studio screenshot and practice-mode restoration")
                finish()
                return
            root.after(80, tick)
        except Exception:
            finish(traceback.format_exc())

    root.after(100, tick)
    root.mainloop()
    return 0 if report["ok"] else 1
