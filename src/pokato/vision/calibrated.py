"""Learned visual templates and amount OCR for arbitrary user-calibrated skins.

Scores are visual similarity, never calibrated probabilities of correctness.
Unknown or ambiguous fields remain unknown; no game-state defaults are guessed.
"""
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import math
import re
from PIL import Image, ImageChops, ImageDraw, ImageStat
from pokato.core.cards import RANKS, SUITS, normalize_notation, validate_cards
from .layouts import Example, field_choices

NUMBER_CHARS = "0123456789.,$€£¥kKmMbB+-"


def foreground(image, contrast=30):
    image = image.convert("RGB")
    image.thumbnail((512, 256), Image.Resampling.LANCZOS)
    small = image.copy()
    small.thumbnail((64, 64), Image.Resampling.BOX)
    quantized = small.quantize(colors=8, method=Image.Quantize.FASTOCTREE)
    background_index = max(quantized.getcolors(), key=lambda item: item[0])[1]
    palette = quantized.getpalette()
    bg = palette[background_index*3:background_index*3+3]
    mask = Image.new("L", image.size)
    mask.putdata([255 if max(abs(c-b) for c, b in zip(pixel, bg)) >= contrast else 0 for pixel in image.getdata()])
    # Fractional scaling can put a one-pixel neighboring background on the ROI
    # edge. Calibration crops require padding around the complete glyph.
    ImageDraw.Draw(mask).rectangle((0, 0, mask.width-1, mask.height-1), outline=0)
    return mask


def normalized(mask):
    box = mask.getbbox()
    result = Image.new("L", (32, 32))
    if box is None:
        return result, 0.
    crop = mask.crop(box)
    aspect = crop.width/crop.height
    scale = 28/max(crop.size)
    crop = crop.resize((max(1, round(crop.width*scale)), max(1, round(crop.height*scale))), Image.Resampling.LANCZOS)
    result.paste(crop, ((32-crop.width)//2, (32-crop.height)//2))
    return result, aspect


def segments(mask):
    columns = [mask.crop((x, 0, x+1, mask.height)).getbbox() is not None for x in range(mask.width)]
    starts, start = [], None
    for x, ink in enumerate(columns+[False]):
        if ink and start is None:
            start = x
        elif not ink and start is not None:
            crop = mask.crop((start, 0, x, mask.height))
            starts.append(crop.crop(crop.getbbox()))
            start = None
    return starts


def label_for(kind, value):
    value = str(value).strip()
    if kind == "rank":
        value = "T" if value == "10" else value.upper()
        if value == "EMPTY":
            return "empty"
        if value not in RANKS or len(value) != 1:
            raise ValueError("Rank label must be 2–9, T, J, Q, K, A or empty")
    elif kind == "suit":
        value = normalize_notation(value).lower()
        if value != "empty" and value not in SUITS:
            raise ValueError("Suit label must be ♣ ♦ ♥ ♠ or empty")
    elif kind == "flag":
        value = {"true": "yes", "false": "no", "1": "yes", "0": "no"}.get(value.lower(), value.lower())
        if value not in ("yes", "no"):
            raise ValueError("Marker label must be yes or no")
    elif kind == "status":
        value = {"active": "A", "folded": "F", "all-in": "I"}.get(value.lower(), value.upper())
        if value not in ("A", "F", "I"):
            raise ValueError("Seat status must be A (in hand), F (out) or I (all-in)")
    elif kind == "anchor":
        if value.lower() != "match":
            raise ValueError("Stable table anchor label must be match")
        value = "match"
    elif kind == "number":
        value = re.sub(r"\s+", "", value)
        if not value or any(c not in NUMBER_CHARS for c in value):
            raise ValueError("Select only the amount text; label its visible digits, currency and punctuation")
    elif kind == "identity":
        raise ValueError("Identity regions are fingerprinted; they do not need examples")
    return value


def parse_amount(text, unit="1", separator=".", multiplier="1"):
    text = re.sub(r"[\s$€£¥]", "", text)
    if text.upper().endswith("BB"):
        text = text[:-2]
    factor = Decimal(1)
    if text[-1:].upper() in ("K", "M"):
        factor = Decimal(1000 if text[-1:].upper() == "K" else 1000000)
        text = text[:-1]
    other = "," if separator == "." else "."
    integer, dot, fraction = text.partition(separator)
    if other in fraction or (other in integer and not re.fullmatch(rf"\+?\d{{1,3}}(?:{re.escape(other)}\d{{3}})+", integer)):
        raise ValueError("Ambiguous thousands/decimal separators")
    text = integer.replace(other, "") + ("."+fraction if dot else "")
    if not re.fullmatch(r"\+?\d+(?:\.\d+)?", text):
        raise ValueError("Amount is not a nonnegative number")
    try:
        amount = Decimal(text)*factor*Decimal(multiplier)/Decimal(unit)
        if not amount.is_finite() or amount < 0 or amount > 10**12 or amount != amount.to_integral_value():
            raise ValueError("Amount does not fit the configured chip unit")
        return int(amount)
    except (InvalidOperation, ZeroDivisionError):
        raise ValueError("Invalid amount or chip unit") from None


@lru_cache(maxsize=4096)
def compiled(example, contrast):
    image = example.image()
    if example.kind == "number":
        parts = segments(foreground(image, contrast))
        if len(parts) != len(example.label):
            raise ValueError("Amount characters touch or the example label does not match the visible text")
        return tuple((char, *normalized(mask)) for char, mask in zip(example.label, parts))
    if example.kind in ("rank", "suit"):
        image, aspect = normalized(foreground(image, contrast))
    else:
        image, aspect = image.resize((48, 32), Image.Resampling.BILINEAR), 1.
    return ((example.label, image, aspect),)


def similarity(image, aspect, reference, reference_aspect):
    if (aspect == 0) != (reference_aspect == 0):
        return 0.
    difference = sum(ImageStat.Stat(ImageChops.difference(image, reference)).mean) / (len(image.getbands())*255)
    penalty = .12*min(1., abs(math.log(aspect/reference_aspect))) if aspect and reference_aspect else 0.
    return max(0., 1-difference-penalty)


def choose(image, aspect, candidates, threshold, margin):
    scores = {}
    for label, reference, reference_aspect in candidates:
        scores[label] = max(scores.get(label, 0.), similarity(image, aspect, reference, reference_aspect))
    if not scores:
        return None, 0., 0., "No labeled examples"
    ordered = sorted(scores.items(), key=lambda row: row[1], reverse=True)
    label, score = ordered[0]
    separation = score - (ordered[1][1] if len(ordered) > 1 else 0.)
    issue = "Low visual similarity" if score < threshold else "Ambiguous visual match" if separation < margin else ""
    return (None if issue else label), score, separation, issue


@dataclass(frozen=True)
class FieldRead:
    name: str
    value: object
    score: float
    margin: float
    box: tuple
    raw: str = ""
    issue: str = ""
    manual: bool = False


@dataclass(frozen=True)
class TableSeat:
    status: str
    stack: int
    bet: int
    identity: str = ""


@dataclass(frozen=True)
class TableSnapshot:
    index: int
    timestamp: float
    hole: tuple
    board: tuple
    pot: int
    seats: tuple
    button: int
    actor: int
    street: str
    score: float
    manual: bool = False


@dataclass(frozen=True)
class TableReading:
    frame: object
    fields: tuple
    snapshot: object
    issues: tuple


class CalibratedReader:
    def __init__(self, layout):
        self.layout = layout.validate()
        self.templates = {}
        for example in layout.examples:
            label_for(example.kind, example.label)
            key = (example.group, example.kind)
            self.templates.setdefault(key, []).extend(compiled(example, layout.contrast))

    @staticmethod
    def teach(layout, region, image, value):
        label = label_for(region.kind, value)
        example = Example.create(region, label, region.crop(image))
        compiled(example, layout.contrast)  # Validate segmentation before saving.
        layout.examples.append(example)
        return example

    def field(self, region, image):
        crop = region.crop(image)
        candidates = self.templates.get((region.template_group, region.kind), ())
        if region.kind == "identity":
            mask, aspect = normalized(foreground(crop, self.layout.contrast))
            value = hashlib.sha256(mask.tobytes()).hexdigest()[:16]
            return FieldRead(region.name, value, 1., 1., region.box, value)
        if region.kind == "number":
            parts = segments(foreground(crop, self.layout.contrast))
            if not parts:
                return FieldRead(region.name, None, 0., 0., region.box, issue="Amount is blank")
            matches = [choose(*normalized(part), candidates, self.layout.threshold, self.layout.margin) for part in parts]
            raw = "".join(label or "?" for label, score, margin, issue in matches)
            issue = next((issue for label, score, margin, issue in matches if issue), "")
            value = None
            if not issue:
                try:
                    value = parse_amount(raw, self.layout.chip_unit, self.layout.decimal_separator, region.multiplier)
                except ValueError as exc:
                    issue = str(exc)
            return FieldRead(region.name, value, min(m[1] for m in matches), min(m[2] for m in matches), region.box, raw, issue)
        if region.kind in ("rank", "suit"):
            mask, aspect = normalized(foreground(crop, self.layout.contrast))
        else:
            mask, aspect = crop.convert("RGB").resize((48, 32), Image.Resampling.BILINEAR), 1.
        label, score, margin, issue = choose(mask, aspect, candidates, self.layout.threshold, self.layout.margin)
        value = label
        if label is not None and region.kind in ("flag", "anchor"):
            value = label in ("yes", "match")
        return FieldRead(region.name, value, score, margin, region.box, label or "", issue)

    def read(self, frame, overrides=None):
        image = frame.image
        rw, rh = self.layout.reference_size
        if abs(image.width/image.height/(rw/rh)-1) > .025:
            return TableReading(frame, (), None, ("Image aspect ratio differs from this layout; recalibrate or crop the table",))
        # Read at the calibrated pixel scale. ROI coordinates still refer to
        # the original frame, which remains available for inspection/export.
        if image.size != (rw, rh):
            image = image.resize((rw, rh), Image.Resampling.NEAREST)
        fields = []
        for region in self.layout.regions.values():
            try:
                found = self.field(region, image)
                if overrides and region.name in overrides:
                    value = label_for(region.kind, overrides[region.name])
                    raw = value
                    if region.kind == "number":
                        value = parse_amount(value, self.layout.chip_unit, self.layout.decimal_separator, region.multiplier)
                    elif region.kind in ("flag", "anchor"):
                        value = value in ("yes", "match")
                    found = replace(found, value=value, score=1., margin=1., raw=raw, issue="", manual=True)
            except ValueError as exc:
                found = FieldRead(region.name, None, 0., 0., region.box, issue=str(exc))
            fields.append(found)
        return self.assemble(frame, tuple(fields))

    def assemble(self, frame, fields):
        found = {f.name: f for f in fields}
        required = [(name, kind) for name, kind in field_choices(self.layout.seat_count) if kind != "identity"]
        issues = [f"{name}: missing region" for name, kind in required if name not in found]
        issues.extend(f"{f.name}: {f.issue}" for f in fields if f.issue)
        for name, kind in required:
            if name in self.layout.regions and self.layout.regions[name].kind != kind:
                issues.append(f"{name}: wrong field type")
        if issues:
            return TableReading(frame, fields, None, tuple(issues))
        value = lambda name: found[name].value
        try:
            if value("anchor") is not True:
                raise ValueError("Stable table anchor did not match")
            def cards(prefix, count):
                result = []
                empty = False
                for i in range(count):
                    rank, suit = value(f"{prefix}{i}.rank"), value(f"{prefix}{i}.suit")
                    if rank == suit == "empty":
                        empty = True
                    elif empty or rank == "empty" or suit == "empty":
                        raise ValueError("Partial or non-contiguous card display; wait for animation to finish")
                    else:
                        result.append(rank+suit)
                return tuple(result)
            hole, board = cards("hole", 2), cards("board", 5)
            validate_cards(hole+board)
            if len(hole) not in (0, 2) or len(board) not in (0, 3, 4, 5):
                raise ValueError("Incomplete cards or board animation")
            seats = tuple(TableSeat("I" if value(f"seat{i}.status") == "A" and value(f"seat{i}.stack") == 0
                                    else value(f"seat{i}.status"), value(f"seat{i}.stack"), value(f"seat{i}.bet"),
                                    found[f"seat{i}.identity"].value if f"seat{i}.identity" in found else "")
                          for i in range(self.layout.seat_count))
            if any(s.status == "I" and s.stack for s in seats):
                raise ValueError("All-in marker disagrees with stack")
            buttons = [i for i in range(len(seats)) if value(f"seat{i}.dealer")]
            actors = [i for i in range(len(seats)) if value(f"seat{i}.actor")]
            if len(buttons) != 1 or len(actors) > 1:
                raise ValueError("Dealer/actor markers are missing or ambiguous")
            actor = actors[0] if actors else -1
            if actor >= 0 and (seats[actor].status != "A" or not seats[actor].stack):
                raise ValueError("Actor marker points to a folded or all-in player")
            street = "X" if not hole else {0: "P", 3: "F", 4: "T", 5: "R"}[len(board)]
            if street != "X" and actor < 0 and sum(s.status == "A" and s.stack > 0 for s in seats) > 1:
                raise ValueError("No acting-player marker; wait for a stable decision")
            pot = value("pot") + (0 if self.layout.pot_includes_bets else sum(s.bet for s in seats))
            if pot < sum(s.bet for s in seats):
                raise ValueError("Pot is smaller than visible bets; check pot convention")
            snapshot = TableSnapshot(frame.index, frame.timestamp, hole, board, pot, seats, buttons[0], actor,
                                     street, min(f.score for f in fields), any(f.manual for f in fields))
            return TableReading(frame, fields, snapshot, ())
        except (ValueError, TypeError) as exc:
            return TableReading(frame, fields, None, (str(exc),))
