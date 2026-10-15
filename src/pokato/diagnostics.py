"""Self-contained GUI smoke check that also runs inside the frozen executable."""
import json
from pathlib import Path
import sys
import time
import traceback
import tkinter as tk
from .app import App
from .vision.capture import capture_widget, enable_dpi_awareness
from .vision.reader import ReadError
from .ui.sizing import geometry, font_pixels


def packaged_smoke(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root, samples=100, database=":memory:")
    started = time.monotonic()
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "executable": sys.executable, "checks": []}

    def finish(error=None):
        report["ok"] = error is None
        if error:
            report["error"] = error
        try:
            app.close()
        except Exception:
            report["ok"] = False
            report["error"] = traceback.format_exc()
            root.quit()
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    root.report_callback_exception = lambda kind, value, tb: finish("".join(traceback.format_exception(kind, value, tb)))

    def check_frame():
        observed = app.reader.read(capture_widget(app.table))
        if observed.hole != tuple(app.game.players[0].hole) or observed.pot != app.game.pot:
            raise AssertionError("Captured state differs from simulator truth")
        if observed.events != tuple(app.game.events[-8:]):
            raise AssertionError("Captured actions differ from simulator truth")
        return observed

    def expanded():
        try:
            if time.monotonic() - started > 40:
                raise TimeoutError("Expanded window capture did not settle")
            check_frame()
            expected_column = int(app.hud_canvas.winfo_width() >= app.hp(740))
            if not app.chrome.maximized or app.detail_column.grid_info()["column"] != expected_column:
                raise AssertionError("Custom maximize or responsive HUD failed")
            report["checks"].append("maximized table recognition and responsive HUD")
            app.chrome.toggle_maximize()
            app.call_action()
            if app.advice is not None or app.current_key is not None:
                raise AssertionError("Action did not invalidate advice")
            report["checks"].append("advice invalidation after an action")
            finish()
        except ReadError:
            root.after(250, expanded)
        except Exception:
            finish(traceback.format_exc())

    def ready():
        try:
            if time.monotonic() - started > 30:
                raise TimeoutError(f"No coaching result: {app.last_error}")
            if app.advice is None:
                root.after(250, ready)
                return
            observed = check_frame()
            if not app.advice.actions or not app.tracker.events:
                raise AssertionError("Missing numerical advice or reconstructed history")
            if not root.overrideredirect() or not app.hud.overrideredirect():
                raise AssertionError("Native frame unexpectedly present")
            if not 0.85 < app.hud.attributes("-alpha") < 1:
                raise AssertionError("HUD transparency is missing")
            body_pixels = abs(app.hud_fonts.get(10).cget("size"))
            if body_pixels < font_pixels(10, app.hud_scale):
                raise AssertionError("HUD text did not scale to the display")
            if app.details_open or app.hud_canvas.winfo_ismapped():
                raise AssertionError("Default HUD should not require scrolling")
            for widget in app.crucial_widgets:
                if widget.winfo_rooty() + widget.winfo_height() > app.hud_chrome.footer.winfo_rooty():
                    raise AssertionError("Crucial HUD content is clipped")
            area_fraction = app.hud.winfo_width() * app.hud.winfo_height() / (app.display.width * app.display.height)
            if app.display.width >= 3000 and not 1 / 16 < area_fraction < 0.08:
                raise AssertionError(f"HUD footprint is wrong: {area_fraction:.1%}")
            report.update(hand=observed.hand, equity=app.advice.equity.share)
            report.update(display_dpi=app.display.dpi, hud_scale=app.hud_scale, body_font_pixels=body_pixels)
            report.update(hud_width=app.hud.winfo_width(), hud_height=app.hud.winfo_height(), hud_area_fraction=area_fraction)
            report["checks"].extend(("window capture and reconstructed history", "equity and action EV",
                                      "frameless windows and translucent HUD", "display-aware readable HUD fonts",
                                      "compact footprint with visible essentials and no scrolling"))
            app.toggle_details()
            app.hud.geometry(geometry(app.hud_display.fit(860 * app.hud_scale, 940 * app.hud_scale)))
            app.chrome.toggle_maximize()
            root.after(700, expanded)
        except Exception:
            finish(traceback.format_exc())

    root.after(500, ready)
    root.mainloop()
    return 0 if report["ok"] else 1
