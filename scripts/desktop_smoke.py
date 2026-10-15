"""Exercise the real Windows screen-capture pipeline, not just rendered buffers.

Run from repository root after installing the package. Owns only the local
practice UI, closes it automatically, and writes ignored QA artifacts.
"""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from PIL import ImageGrab
from pokato.app import App
from pokato.vision.capture import enable_dpi_awareness
from pokato.vision.capture import capture_widget


def main():
    enable_dpi_awareness()
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    app = App(root, samples=100, database=":memory:")
    failure = []
    started = time.monotonic()

    def inspect():
        try:
            if time.monotonic() - started > 35:
                raise AssertionError(f"Timed out: {app.last_error or app.recommendation.cget('text')}")
            if app.advice is None:
                root.after(250, inspect)
                return
            o = app.latest
            assert o.actor == 0, "Advice must be tied to hero's turn"
            assert o.hole == tuple(app.game.players[0].hole)
            assert o.pot == app.game.pot
            assert tuple(app.tracker.events) == tuple(app.game.events)
            assert app.advice.actions, "Expected supported action EVs"
            capture_widget(app.table).save(output / "desktop-smoke-table.png")
            ImageGrab.grab(window=root.winfo_id()).save(output / "desktop-smoke.png")
            ImageGrab.grab(window=app.hud.winfo_id()).save(output / "desktop-smoke-hud.png")
            (output / "desktop-smoke.json").write_text(json.dumps({
                "input": "actual desktop pixels", "hand": o.hand, "hole": o.hole,
                "events": len(app.tracker.events), "equity": app.advice.equity.share,
                "recommendation": app.advice.recommendation,
            }, indent=2), encoding="utf-8")
            app.call_action()
            assert app.advice is None
            assert app.current_key is None
            assert app.action_label.cget("text") == ""
            print("PASS: actual screen capture -> reconstructed history -> equity/EV -> HUD")
            app.close()
        except Exception as exc:
            failure.append(str(exc))
            print(f"FAIL: {exc}")
            capture_widget(app.table).save(output / "desktop-smoke-failure.png")
            app.close()

    root.after(500, inspect)
    root.mainloop()
    return int(bool(failure))


if __name__ == "__main__":
    sys.exit(main())
