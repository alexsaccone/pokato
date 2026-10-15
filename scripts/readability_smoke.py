"""Exercise real widgets at simulated common work areas without changing OS settings."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from dataclasses import replace
from PIL import ImageGrab
from pokato.app import App
from pokato.ui.sizing import Display, Preferences, font_pixels
from pokato.vision.capture import capture_widget, enable_dpi_awareness
from pokato.analysis.coach import Advice, ActionValue
from pokato.analysis.equity import Equity


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
                        assert abs(app.hud_fonts.get(10).cget("size")) >= font_pixels(10, display.compact_scale)
                        assert not app.details_open and not app.hud_canvas.winfo_ismapped()
                        # Fill the overlay with a full river and all three EVs,
                        # rather than verifying only empty/waiting-state labels.
                        app.update_observed(replace(o, street="R", board=("As", "Kh", "Qd", "Jc", "Ts"), pot=12345, call=1000))
                        app.show_advice(Advice(Equity(0.42, 0.01, 600), 0.25,
                            (ActionValue("Raise to 1000", 12.3), ActionValue("Call", 10.1), ActionValue("Fold", 0)),
                            "Raise to 1000 · best modeled EV", "UI fixture: details remain optional.", "Straight"))
                        stage.append(abs(app.hud_fonts.get(10).cget("size")))
                        stage[0] = 1
                    elif stage[0] == 1:
                        assert_essentials(app)
                        if display.width >= 3000:
                            ratio = app.hud.winfo_width() * app.hud.winfo_height() / (display.width * display.height)
                            assert 1 / 16 < ratio < 0.08, ratio
                        app.details_button.invoke()
                        stage[0] = 2
                    elif stage[0] == 2:
                        assert app.details_open and app.hud_canvas.winfo_ismapped()
                        assert_essentials(app)
                        app.details_button.invoke()
                        stage[0] = 3
                    elif stage[0] == 3:
                        assert not app.details_open and not app.hud_canvas.winfo_ismapped()
                        assert_essentials(app)
                        app.zoom_in.invoke()
                        stage[0] = 4
                    elif stage[0] == 4:
                        assert abs(app.hud_fonts.get(10).cget("size")) > stage[1]
                        assert Preferences(settings).zoom == 1.1
                        assert app.hud.winfo_x() + app.hud.winfo_width() <= display.width
                        assert app.hud.winfo_y() + app.hud.winfo_height() <= display.height
                        app.zoom_reset.invoke()
                        stage[0] = 5
                    else:
                        assert app.hud_zoom == 1.0
                        assert abs(app.hud_fonts.get(10).cget("size")) == stage[1]
                        assert_essentials(app)
                        if display.width >= 3000:
                            ratio = app.hud.winfo_width() * app.hud.winfo_height() / (display.width * display.height)
                            assert ratio < 0.08, ("Reset did not restore compact size", ratio)
                        assert not app.hud_chrome.hint.winfo_ismapped()
                        ImageGrab.grab(window=app.hud.winfo_id()).save(output / f"readability-{name}.png")
                        print(f"PASS: {name}, body {stage[1]}px, visible essentials, optional detail, saved zoom, table capture")
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


def assert_essentials(app):
    """Every crucial widget must fit inside the non-scrolling content region."""
    x, y = app.hud.winfo_rootx(), app.hud.winfo_rooty()
    footer_y = app.hud_chrome.footer.winfo_rooty() - y
    for widget in app.crucial_widgets:
        assert widget.winfo_ismapped(), str(widget)
        wx, wy = widget.winfo_rootx() - x, widget.winfo_rooty() - y
        assert wx >= 0 and wy >= 0, (str(widget), wx, wy)
        assert wx + widget.winfo_width() <= app.hud.winfo_width(), str(widget)
        assert wy + widget.winfo_height() <= footer_y, (str(widget), wy, widget.winfo_height(), footer_y)
        assert widget.winfo_width() >= widget.winfo_reqwidth(), (str(widget), "text clipped horizontally")


if __name__ == "__main__":
    sys.exit(main())
