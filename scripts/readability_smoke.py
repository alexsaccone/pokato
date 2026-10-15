"""Exercise real widgets at simulated common work areas without changing OS settings."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from PIL import ImageGrab
from pokato.app import App
from pokato.ui.sizing import Display, Preferences, font_pixels
from pokato.vision.capture import capture_widget, enable_dpi_awareness


def main():
    enable_dpi_awareness()
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    failures = []
    for name, display in (("laptop-768p", Display(0, 0, 1366, 728, 96)),
                          ("laptop-768p-150", Display(0, 0, 1366, 728, 144)),
                          ("desktop-1080p", Display(0, 0, 1920, 1040, 96)),
                          ("desktop-1080p-150", Display(0, 0, 1920, 1040, 144)),
                          ("laptop-4k", Display(0, 0, 3840, 2280, 240))):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.json"
            root = tk.Tk()
            app = App(root, database=":memory:", samples=100, display=display, settings_path=settings)
            app.paused = True
            started = time.monotonic()
            stage = [0]

            def check():
                try:
                    if time.monotonic() - started > 12:
                        raise TimeoutError("Readability smoke check did not settle")
                    if stage[0] == 0:
                        for window in (root, app.hud):
                            assert window.winfo_width() <= display.width
                            assert window.winfo_height() <= display.height
                            assert window.winfo_y() + window.winfo_height() <= display.height
                        o = app.reader.read(capture_widget(app.table))
                        assert o.hole == tuple(app.game.players[0].hole)
                        assert abs(app.hud_fonts.get(10).cget("size")) >= font_pixels(10, display.scale)
                        assert app.detail_column.grid_info()["column"] == 0
                        stage.append(abs(app.hud_fonts.get(10).cget("size")))
                        app.zoom_in.invoke()
                        stage[0] = 1
                    elif stage[0] == 1:
                        assert abs(app.hud_fonts.get(10).cget("size")) > stage[1]
                        assert Preferences(settings).zoom == 1.1
                        assert app.hud.winfo_x() + app.hud.winfo_width() <= display.width
                        assert app.hud.winfo_y() + app.hud.winfo_height() <= display.height
                        app.zoom_reset.invoke()
                        stage[0] = 2
                    else:
                        assert app.hud_zoom == 1.0
                        assert abs(app.hud_fonts.get(10).cget("size")) == stage[1]
                        app.hud_canvas.yview_moveto(1.0)
                        assert app.hud_canvas.yview()[1] > 0.99
                        ImageGrab.grab(window=app.hud.winfo_id()).save(output / f"readability-{name}.png")
                        print(f"PASS: {name}, body {stage[1]}px, auto-fit, zoom persistence, scroll, table capture")
                        app.close()
                        return
                    root.after(400, check)
                except Exception as exc:
                    failures.append(f"{name}: {type(exc).__name__}: {exc}")
                    print(f"FAIL: {failures[-1]}")
                    ImageGrab.grab(window=app.hud.winfo_id()).save(output / f"readability-{name}-failure.png")
                    app.close()

            root.after(600, check)
            root.mainloop()
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
