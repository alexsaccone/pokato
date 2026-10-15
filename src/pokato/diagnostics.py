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
        if error:
            report["error"] = error
        else:
            report["ok"] = True
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.close()

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
            if not app.chrome.maximized or app.detail_column.grid_info()["column"] != 1:
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
            report.update(hand=observed.hand, equity=app.advice.equity.share)
            report["checks"].extend(("window capture and reconstructed history", "equity and action EV",
                                      "frameless windows and translucent HUD"))
            app.hud.geometry("860x940+30+30")
            app.chrome.toggle_maximize()
            root.after(700, expanded)
        except Exception:
            finish(traceback.format_exc())

    root.after(500, ready)
    root.mainloop()
    return 0 if report["ok"] else 1
