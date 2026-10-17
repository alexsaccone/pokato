"""Check the default HUD's real widget bounds at common display sizes."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from PIL import ImageGrab
from pokato.ui.automatic_hud import AutomaticHUD
from pokato.ui.sizing import Display, Preferences, font_pixels
from pokato.ui.window import NativeWindow
from pokato.vision.automatic import AutoReading, Amount, Card
from pokato.vision.capture import enable_dpi_awareness


def inside(widget, parent):
    assert widget.winfo_ismapped(), (str(widget), 'not mapped')
    x = widget.winfo_rootx()-parent.winfo_rootx()
    y = widget.winfo_rooty()-parent.winfo_rooty()
    assert 0 <= x and 0 <= y, (str(widget), x, y, widget.winfo_height(), parent.winfo_height())
    assert x+widget.winfo_width() <= parent.winfo_width()+2
    assert y+widget.winfo_height() <= parent.winfo_height()+2


def main():
    enable_dpi_awareness()
    output = Path('artifacts')
    output.mkdir(exist_ok=True)
    report = []
    for name, display in (('768p', Display(0, 0, 1366, 728, 96)),
                          ('768p-150', Display(0, 0, 1366, 728, 144)),
                          ('1080p', Display(0, 0, 1920, 1040, 96)),
                          ('1080p-150', Display(0, 0, 1920, 1040, 144)),
                          ('4k-250', Display(0, 0, 3840, 2280, 240))):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            settings = Path(folder)/'settings.json'
            hud = AutomaticHUD(root, display=display, settings_path=settings)
            try:
                reading = AutoReading(
                    board=tuple(Card((0, 0, 1, 1), value[0], value[1], 1.)
                                for value in ('Ac', '7d', 'Ts', '2h', '9c')),
                    hand=(Card((0, 0, 1, 1), 'K', 'c', 1.), Card((0, 0, 1, 1), 'K', 'h', 1.)),
                    pots=(Amount('125.50', '125.50', False, 'pot'),),
                    hero_verified=True, table_found=True)
                hud.deliver(reading)
                root.update()
                assert root.winfo_width() <= display.width and root.winfo_height() <= display.height
                assert abs(hud.fonts.get(10).cget('size')) == font_pixels(10, display.compact_scale)
                if display.width >= 3000:
                    assert abs(hud.fonts.get(10).cget('size')) >= 30
                for widget in (hud.start_button, hud.menu_button, hud.footer, hud.cards, hud.status):
                    inside(widget, root)
                for item in hud.cards.find_all():
                    box = hud.cards.bbox(item)
                    assert box[0] >= 0 and box[2] <= hud.cards.winfo_width(), ('card clipped', name, box)
                assert hud.start_button.winfo_width() >= hud.start_button.winfo_reqwidth()
                ImageGrab.grab(window=NativeWindow(root).handle).save(output/f'automatic-{name}.png')
                hud.set_zoom(2.)
                root.update()
                inside(hud.start_button, root)
                assert hud.reading is reading and not hud.running
                hud.panel.canvas.yview_moveto(1.)
                root.update()
                inside(hud.detail, hud.panel.canvas)
                assert Preferences(settings, key='automatic_zoom').zoom == 2.
                report.append({'display': name, 'ok': True, 'body_pixels': font_pixels(10, display.compact_scale)})
            finally:
                hud.close()
    (output/'automatic-readability.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
