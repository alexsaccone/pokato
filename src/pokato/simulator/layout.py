"""Versioned, visible table layout shared by renderer and pixel recognizer.

These coordinates are calibration, not a channel for hidden game state.
Every field is ordinary readable text, also visible to the player.
"""
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 980, 800
CELL_W, CELL_H = 12, 22
INK, FIELD_BG = (226, 238, 232), (15, 31, 29)
ALPHABET = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZcdhs-"


@lru_cache(maxsize=32)
def font(size=15, mono=False):
    paths = (["C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
             if mono else ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


@dataclass(frozen=True)
class Field:
    x: int
    y: int
    length: int

    @property
    def box(self):
        return self.x, self.y, self.x + self.length * CELL_W, self.y + CELL_H


SEATS = [(402, 499), (104, 422), (104, 186), (402, 130), (700, 186), (700, 422)]
FIELDS = {
    "marker": Field(24, 59, 9), "hand": Field(217, 59, 8),
    "street": Field(405, 59, 1), "actor": Field(499, 59, 1),
    "button": Field(594, 59, 1), "pot": Field(438, 260, 7),
    "call": Field(93, 649, 7), "minimum": Field(365, 649, 7),
    "maximum": Field(654, 649, 7),
}
for i, (x, y) in enumerate(SEATS):
    FIELDS[f"status{i}"] = Field(x + 132, y + 8, 1)
    FIELDS[f"stack{i}"] = Field(x + 70, y + 38, 7)
    FIELDS[f"bet{i}"] = Field(x + 70, y + 61, 7)
    FIELDS[f"invested{i}"] = Field(x + 70, y + 84, 7)
for i in range(5):
    FIELDS[f"board{i}"] = Field(328 + i * 68, 325, 2)
for i in range(2):
    FIELDS[f"hole{i}"] = Field(458 + i * 44, 470, 2)
# Readable event tape: seq, seat, street, action, additional chips.
for i in range(8):
    FIELDS[f"event{i}"] = Field(24 + (i // 4) * 480, 706 + (i % 4) * 22, 18)


@lru_cache(maxsize=64)
def glyph(character):
    image = Image.new("RGB", (CELL_W, CELL_H), FIELD_BG)
    ImageDraw.Draw(image).text((1, 1), character, font=font(15, mono=True), fill=INK)
    return image


def paint_field(image, key, value):
    field = FIELDS[key]
    value = str(value)
    if len(value) > field.length:
        raise ValueError(f"{key} exceeds supported field width")
    for n, char in enumerate(value.ljust(field.length)):
        image.paste(glyph(char), (field.x + n * CELL_W, field.y))
