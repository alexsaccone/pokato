"""Actual reader widgets at common DPI/work areas; no OS setting changes."""
from pathlib import Path
import json
import tempfile
import time
import tkinter as tk
import tkinter.font as tkfont
from PIL import ImageGrab
from pokato.app import App
from pokato.ui.sizing import Display, Preferences, font_pixels
from pokato.ui.window import NativeWindow
from pokato.vision.capture import enable_dpi_awareness


def within(widget, parent):
    assert widget.winfo_ismapped(), (str(widget), "not mapped")
    x, y = widget.winfo_rootx()-parent.winfo_rootx(), widget.winfo_rooty()-parent.winfo_rooty()
    assert x >= 0 and y >= 0, (str(widget), x, y)
    assert x+widget.winfo_width() <= parent.winfo_width()+2, (str(widget), "horizontal clipping")
    assert y+widget.winfo_height() <= parent.winfo_height()+2, (str(widget), "vertical clipping", y, widget.winfo_height(), parent.winfo_height())


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main(only=None):
    enable_dpi_awareness()
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    failures = []
    for name, display in (("768p", Display(0, 0, 1366, 728, 96)),
                          ("768p-150", Display(0, 0, 1366, 728, 144)),
                          ("1080p", Display(0, 0, 1920, 1040, 96)),
                          ("1080p-150", Display(0, 0, 1920, 1040, 144)),
                          ("4k-250", Display(0, 0, 3840, 2280, 240))):
        if only and name != only:
            continue
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder)/"settings.json"
            Preferences(settings).save(1.2)
            root = tk.Tk()
            app = App(root, database=":memory:", samples=100, display=display, settings_path=settings)
            app.paused = True
            practice_font = app.hud_fonts.get(10).cget("size")
            studio = app.open_table_reader()
            studio.open_demo()
            stage, started = 0, time.monotonic()
            frame_signature = None
            dialog = None

            def tick():
                nonlocal stage, dialog, frame_signature
                try:
                    root.update_idletasks()
                    assert time.monotonic()-started < 30, ("timed out", stage)
                    if not studio.frame or studio.future is not None:
                        root.after(100, tick)
                        return
                    if stage == 0:
                        body = studio.theme.fonts.get(10)
                        assert abs(body.cget("size")) == font_pixels(10, display.scale)
                        if display.width >= 3000:
                            assert abs(body.cget("size")) >= 40
                        for bar in studio.toolbars:
                            if not bar.winfo_ismapped():
                                continue
                            for child in bar.winfo_children():
                                if child.winfo_class() == "Menu":
                                    continue
                                within(child, studio.window)
                                assert child.winfo_width() >= child.winfo_reqwidth()
                        assert studio.window.winfo_width() <= display.width
                        assert studio.window.winfo_height() <= display.height
                        frame_signature = (studio.frame.image.tobytes(), tuple(studio.layout.regions.items()),
                                           studio.generation, studio.result.events)
                        studio.pane_choice.set("readings")
                        studio.layout_panes()
                        stage = 1
                    elif stage == 1:
                        # Real row bounds must contain the actual font metrics.
                        box = studio.fields.bbox("anchor")
                        assert box and box[3] >= studio.theme.fonts.get(10).metrics("linespace"), box
                        popup = studio.field_combo.tk.call("ttk::combobox::PopdownWindow", str(studio.field_combo))
                        popup_font = studio.field_combo.tk.call(f"{popup}.f.l", "cget", "-font")
                        assert tkfont.Font(root=root, font=popup_font).metrics("linespace") == studio.theme.fonts.get(10).metrics("linespace")
                        studio.selected_box = (.1, .1, .2, .2)
                        studio.group.set("pending-font-group")
                        studio.multiplier.set("2")
                        studio.foreground.set("card")
                        studio.set_zoom(1.1)
                        stage = 2
                    elif stage == 2:
                        assert Preferences(settings, key="reader_zoom").zoom == 1.1
                        assert Preferences(settings).zoom == 1.2
                        assert app.hud_fonts.get(10).cget("size") == practice_font
                        assert studio.selected_box == (.1, .1, .2, .2)
                        assert studio.group.get() == "pending-font-group" and studio.multiplier.get() == "2"
                        assert studio.foreground.get() == "card"
                        assert (studio.frame.image.tobytes(), tuple(studio.layout.regions.items()), studio.generation,
                                studio.result.events) == frame_signature
                        studio.select_field()
                        studio.set_zoom(2.)
                        studio.pane_choice.set("table")
                        studio.layout_panes()
                        stage = 3
                    elif stage == 3:
                        for bar in studio.toolbars:
                            if not bar.winfo_ismapped():
                                continue
                            for child in bar.winfo_children():
                                if child.winfo_class() == "Menu":
                                    continue
                                within(child, studio.window)
                        studio.visual_panel.canvas.yview_moveto(1.)
                        stage = 4
                    elif stage == 4:
                        # The bottom guidance must be reachable at 200% zoom.
                        studio.visual_panel.canvas.yview_moveto(1.)
                        root.update_idletasks()
                        within(studio.reader_note, studio.visual_panel.canvas)
                        studio.set_zoom(1.)
                        dialog = studio.settings()
                        stage = 5
                    elif stage == 5:
                        assert dialog.winfo_width() <= display.width
                        assert dialog.winfo_height() <= display.height
                        for child in descendants(dialog):
                            if child.winfo_class() == "TEntry":
                                assert tkfont.Font(root=root, font=child.cget("font")).metrics("linespace") == studio.theme.fonts.get(10).metrics("linespace")
                        for child in dialog.footer.winfo_children():
                            within(child, dialog)
                        if display.width >= 3000:
                            ImageGrab.grab(window=NativeWindow(dialog).handle).save(output/f"reader-settings-{name}.png")
                        dialog.destroy()
                        dialog = studio.manage_examples()
                        stage = 6
                    elif stage == 6:
                        listing = next(w for w in descendants(dialog) if w.winfo_class() == "Listbox")
                        assert tkfont.Font(root=root, font=listing.cget("font")).metrics("linespace") == studio.theme.fonts.get(10).metrics("linespace")
                        dialog.destroy()
                        studio.field.set("pot")
                        dialog = studio.correct_field()
                        stage = 7
                    elif stage == 7:
                        entry = next(w for w in descendants(dialog) if w.winfo_class() == "TEntry")
                        entry.insert(0, "$0.15")
                        apply = next(w for w in dialog.footer.winfo_children() if w.cget("text") == "Apply correction")
                        apply.invoke()
                        stage = 8
                    else:
                        assert studio.reading.snapshot.manual and studio.result.quality == "gap"
                        studio.open_demo()
                        studio.show_hud()
                        stage = 9
                    if stage == 9:
                        root.after(700, finish)
                    else:
                        root.after(400, tick)
                except Exception as exc:
                    failures.append(f"{name}, stage {stage}: {type(exc).__name__}: {exc}")
                    print("FAIL:", failures[-1])
                    debug = [{"geometry": bar.winfo_geometry(), "mapped": bar.winfo_ismapped(), "req": [bar.winfo_reqwidth(), bar.winfo_reqheight()],
                              "children": [{"class": w.winfo_class(), "geometry": w.winfo_geometry(), "mapped": w.winfo_ismapped()}
                                           for w in bar.winfo_children()]} for bar in studio.toolbars]
                    (output/f"reader-layout-{name}.json").write_text(json.dumps(debug, indent=2))
                    ImageGrab.grab(window=NativeWindow(studio.window).handle).save(output/f"reader-readability-{name}-failure.png")
                    app.close()

            def finish():
                try:
                    assert studio.hud.winfo_width() <= display.width
                    assert studio.hud.winfo_height() <= display.height
                    assert abs(studio.hud_fonts.get(10).cget("size")) >= font_pixels(10, display.compact_scale)
                    assert not studio.hud_chrome.hint.winfo_ismapped()
                    studio.hud.withdraw()
                    studio.window.lift()
                    root.update_idletasks()
                    ImageGrab.grab(window=NativeWindow(studio.window).handle).save(output/f"reader-readability-{name}.png")
                    print(f"PASS: {name}, {abs(studio.theme.fonts.get(10).cget('size'))}px body, scaled rows/dialogs, saved independent zoom, reachable controls")
                except Exception as exc:
                    failures.append(f"{name}, finish: {exc}")
                    print("FAIL:", failures[-1])
                app.close()

            root.after(700, tick)
            root.mainloop()
    return int(bool(failures))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    raise SystemExit(main(parser.parse_args().case))
