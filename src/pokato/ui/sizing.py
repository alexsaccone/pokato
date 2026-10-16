"""Display-aware sizing independent of the table's optical reference pixels."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import tkinter.font as tkfont


@dataclass(frozen=True)
class Display:
    x: int
    y: int
    width: int
    height: int
    dpi: int = 96

    @property
    def scale(self):
        # Dense laptop panels should remain readable even if Windows was left
        # at 100%. Physical diagonal cannot be reliably inferred from resolution.
        floor = 2.0 if self.width >= 3000 and self.height >= 1700 else 1.0
        return min(4.0, max(floor, self.dpi / 96, 1.0))

    @property
    def margin(self):
        return min(round(24 * self.scale), max(8, self.height // 20))

    def fit(self, width, height, x=None, y=None):
        m = self.margin
        width = min(round(width), self.width - 2 * m)
        height = min(round(height), self.height - 2 * m)
        x = self.x + m if x is None else x
        y = self.y + m if y is None else y
        x = max(self.x, min(round(x), self.x + self.width - width))
        y = max(self.y, min(round(y), self.y + self.height - height))
        return width, height, x, y

    def hud_rect(self, zoom=1.0, beside=None):
        # Text zoom is independent of footprint. Keep the default overlay near
        # 7% of usable screen area, with a readable floor on smaller displays.
        area = self.width * self.height * 0.07
        width = max(500, round(math.sqrt(area * 1.5)))
        height = max(340, round(area / width))
        width, height, _, _ = self.fit(width, height)
        x = beside if beside is not None else self.x + self.width - width - self.margin
        return self.fit(width, height, x, self.y + self.margin)

    @property
    def compact_scale(self):
        width, height, _, _ = self.hud_rect()
        return min(self.scale, max(1.0, min(width / 500, height / 340)))

    def table_rect(self):
        width = max(min(1004, self.width - 2 * self.margin), min(1040 * self.scale, self.width * 0.64))
        return self.fit(width, 970 * self.scale)

    @staticmethod
    def detect(window):
        from .window import NativeWindow
        native = NativeWindow(window)
        return Display(*native.work_area(), native.dpi())


def geometry(rect):
    width, height, x, y = rect
    return f"{width}x{height}{x:+d}{y:+d}"


def font_pixels(size, scale):
    return max(11, round(max(14, size * 1.6) * scale))


class HudFonts:
    """Named pixel fonts update all HUD widgets when zoom/DPI changes."""
    def __init__(self, window, scale):
        self.window, self.scale = window, scale
        self.fonts = {}

    def get(self, size=10, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(root=self.window, family="Segoe UI", size=-font_pixels(size, self.scale),
                                         weight="bold" if bold else "normal")
        return self.fonts[key]

    def set_scale(self, scale):
        self.scale = scale
        for (size, _), font in self.fonts.items():
            font.configure(size=-font_pixels(size, scale))


class Preferences:
    def __init__(self, path=None, key="hud_zoom"):
        self.key = key
        self.path = None if path is False else Path(path or Path.home() / ".pokato" / "settings.json")
        self.zoom = 1.0
        if self.path:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8")).get(self.key, 1.0)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.8 <= value <= 2.0:
                    self.zoom = round(value, 2)
            except (OSError, ValueError, AttributeError):
                pass

    def save(self, zoom):
        self.zoom = round(max(0.8, min(2.0, zoom)), 2)
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    settings = json.loads(self.path.read_text(encoding="utf-8"))
                    if not isinstance(settings, dict):
                        settings = {}
                except (OSError, ValueError):
                    settings = {}
                settings[self.key] = self.zoom
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                pass
