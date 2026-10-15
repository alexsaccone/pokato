"""Interactive regression check for custom window controls and scaled capture."""
from pathlib import Path
import sys
import time
import tkinter as tk
from PIL import ImageGrab
from pokato.app import App
from pokato.vision.capture import capture_widget, enable_dpi_awareness
from pokato.simulator.layout import WIDTH, HEIGHT
from pokato.vision.reader import ReadError
from pokato.ui.sizing import geometry


def main():
    enable_dpi_awareness()
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    app = App(root, samples=100, database=":memory:")
    app.paused = True
    failed = []
    initial = {}

    def read_table():
        frame = capture_widget(app.table)
        frame.save(output / "window-smoke-capture.png")
        observed = app.reader.read(frame)
        assert observed.hole == tuple(app.game.players[0].hole)
        assert observed.pot == app.game.pot
        assert observed.events == tuple(app.game.events[-8:])
        return observed

    def original():
        assert root.overrideredirect() and app.hud.overrideredirect()
        assert 0.85 <= app.hud.attributes("-alpha") < 1
        initial["geometry"] = root.geometry()
        app.opacity_button.invoke()
        assert abs(app.hud.attributes("-alpha") - 0.88) < 0.01
        app.opacity_button.invoke()
        app.opacity_button.invoke()
        read_table()
        # Exercise the grip's real event bindings, not just geometry().
        grip = app.chrome.grip
        initial["size"] = (root.winfo_width(), root.winfo_height())
        grip.event_generate("<ButtonPress-1>", x=3, y=3)
        grip.event_generate("<B1-Motion>", x=183, y=123)

    def resized():
        assert root.winfo_width() > initial["size"][0]
        assert root.winfo_height() > initial["size"][1]
        read_table()
        app.chrome.max_button.invoke()

    def maximized():
        assert app.chrome.maximized
        assert app.table.winfo_width() > WIDTH and app.table.winfo_height() > HEIGHT
        read_table()
        ImageGrab.grab(window=root.winfo_id()).save(output / "window-smoke-table-maximized.png")
        app.chrome.max_button.invoke()
        app.hud.geometry(geometry(app.hud_display.fit(860 * app.hud_scale, 940 * app.hud_scale)))

    def wide_hud():
        assert not app.chrome.maximized
        assert app.detail_column.grid_info()["column"] == 1
        assert app.analysis_column.winfo_width() > 350
        ImageGrab.grab(window=app.hud.winfo_id()).save(output / "window-smoke-hud-wide.png")
        # Drag the title bar and verify the custom move gesture.
        initial["hud_x"] = app.hud.winfo_x()
        app.hud_chrome.header.event_generate("<ButtonPress-1>", x=150, y=20)
        app.hud_chrome.header.event_generate("<B1-Motion>", x=205, y=45)

    def dragged():
        assert app.hud.winfo_x() == initial["hud_x"] + 55
        app.hud.geometry("400x800+1080+24")
        app.chrome.min_button.invoke()

    def minimized():
        assert app.chrome.native.minimized()
        assert app.advice is None
        app.chrome.restore()

    def restored():
        assert not app.chrome.native.minimized()
        assert app.detail_column.grid_info()["column"] == 0
        read_table()
        app.hud_chrome.max_button.invoke()

    def hud_maximized():
        assert app.hud_chrome.maximized
        app.hud_chrome.max_button.invoke()
        app.hud_chrome.close_button.invoke()
        assert not app.hud.winfo_viewable()
        app.open_hud()

    def finish():
        assert app.hud.winfo_viewable()
        assert root.overrideredirect() and app.hud.overrideredirect()
        print("PASS: frameless controls, transparency, drag/resize, maximize/restore, responsive HUD, scaled capture")
        app.close()

    steps = iter((original, resized, maximized, wide_hud, dragged, minimized, restored, hud_maximized, finish))
    pending = [None, 0.0]

    def step():
        try:
            if pending[0] is None:
                pending[:] = [next(steps), time.monotonic()]
            operation = pending[0]
            operation()
            pending[0] = None
            if not app.closed:
                root.after(450, step)
        except ReadError as exc:
            # WM_PRINT can briefly see the previous backing pixels during a
            # live window resize. The app also withholds advice until repaint.
            if time.monotonic() - pending[1] < 5:
                root.after(200, step)
            else:
                failed.append(str(exc))
                print(f"FAIL: {exc}")
                app.close()
        except Exception as exc:
            failed.append(str(exc))
            print(f"FAIL: {type(exc).__name__}: {exc}")
            try:
                ImageGrab.grab(window=root.winfo_id()).save(output / "window-smoke-failure.png")
            finally:
                app.close()

    root.after(600, step)
    root.mainloop()
    return int(bool(failed))


if __name__ == "__main__":
    sys.exit(main())
