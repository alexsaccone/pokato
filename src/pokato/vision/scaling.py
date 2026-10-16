"""Glyph calibration for the practice skin at compact nearest-neighbor scales."""
from functools import lru_cache
from PIL import Image
from pokato.simulator.layout import WIDTH, HEIGHT, CELL_W, CELL_H, ALPHABET, FIELD_BG, glyph
from pokato.core.cards import SUIT_SYMBOLS


@lru_cache(maxsize=32)
def sampling_map(reference, displayed):
    axis = Image.new("I", (reference, 1))
    axis.putdata(range(reference))
    axis = axis.resize((displayed, 1), Image.Resampling.NEAREST).resize((reference, 1), Image.Resampling.NEAREST)
    return tuple(axis.getpixel((x, 0)) for x in range(reference))


@lru_cache(maxsize=256)
def sampled_templates(xs, ys):
    result = {}
    for char in ALPHABET:
        pixels = glyph(char).load()
        image = Image.new("RGB", (CELL_W, CELL_H), FIELD_BG)
        image.putdata([pixels[x, y] if 0 <= x < CELL_W and 0 <= y < CELL_H else FIELD_BG
                       for y in ys for x in xs])
        # Resampling can pick the neighboring field's background at its edge.
        # Compare interiors; the glyph's blank padding is not evidence.
        result[char] = image.crop((2, 2, CELL_W - 2, CELL_H - 2))
    return result


def templates_at(x, y, size):
    xs = tuple(value - x for value in sampling_map(WIDTH, size[0])[x:x + CELL_W])
    ys = tuple(value - y for value in sampling_map(HEIGHT, size[1])[y:y + CELL_H])
    return sampled_templates(xs, ys)


def alphabet_at(key, offset):
    if key == "marker":
        return "POKATO-V1"[offset]
    if key.startswith(("board", "hole")):
        return "23456789TJQKA-" if offset == 0 else "cdhs-" + "".join(SUIT_SYMBOLS.values())
    if key.startswith("status"):
        return "AFI"
    if key == "street":
        return "PFTRX"
    if key == "actor":
        return "012345X"
    if key == "button":
        return "012345"
    if key.startswith("event"):
        if offset in (4, 6, 8, 10):
            return " "
        if offset == 5:
            return "012345 "
        if offset == 7:
            return "PFTR "
        if offset == 9:
            return "BFKCR "
    return "0123456789 "
