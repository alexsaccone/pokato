"""Portable, client-independent calibration data. No executable profile content."""
from dataclasses import dataclass, field, asdict
import base64
from io import BytesIO
import json
import math
from pathlib import Path
import re
import uuid
from PIL import Image

KINDS = ("rank", "suit", "number", "flag", "status", "anchor", "identity")


@dataclass(frozen=True)
class Region:
    name: str
    box: tuple
    kind: str
    group: str = ""

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r"[a-z][a-z0-9_.]{0,63}", self.name):
            raise ValueError("Region needs a short field name")
        if self.kind not in KINDS or len(self.box) != 4 or not all(
                type(x) in (int, float) and math.isfinite(x) for x in self.box):
            raise ValueError("Invalid region type or coordinates")
        x0, y0, x1, y1 = self.box
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("Select a nonempty region inside the image")
        if not isinstance(self.group, str) or len(self.group) > 80:
            raise ValueError("Invalid template group")

    @property
    def template_group(self):
        return self.group or (self.kind if self.kind in ("rank", "suit", "number") else self.name)

    def pixels(self, size):
        w, h = size
        x0, y0, x1, y1 = self.box
        box = (round(x0*w), round(y0*h), round(x1*w), round(y1*h))
        if box[2]-box[0] < 2 or box[3]-box[1] < 2:
            raise ValueError(f"{self.name}: region is too small at this resolution")
        return box

    def crop(self, image):
        return image.crop(self.pixels(image.size))


@dataclass(frozen=True)
class Example:
    group: str
    kind: str
    label: str
    png: str

    @classmethod
    def create(cls, region, label, crop):
        # Bound profile size; retain sufficient pixels for glyph calibration.
        image = crop.convert("RGB")
        image.thumbnail((256, 256), Image.Resampling.LANCZOS)
        stream = BytesIO()
        image.save(stream, format="PNG")
        return cls(region.template_group, region.kind, str(label), base64.b64encode(stream.getvalue()).decode("ascii"))

    def image(self):
        if not isinstance(self.png, str) or len(self.png) > 400000:
            raise ValueError("Calibration example is too large")
        raw = base64.b64decode(self.png, validate=True)
        with Image.open(BytesIO(raw)) as image:
            if image.format != "PNG" or max(image.size) > 256 or min(image.size) < 1:
                raise ValueError("Invalid calibration example image")
            return image.convert("RGB")


@dataclass
class Layout:
    name: str = "New table layout"
    reference_size: tuple = (980, 800)
    seat_count: int = 6
    chip_unit: str = "1"
    decimal_separator: str = "."
    small_blind: int = 5
    big_blind: int = 10
    threshold: float = .94
    margin: float = .025
    contrast: int = 30
    regions: dict = field(default_factory=dict)
    examples: list = field(default_factory=list)

    def validate(self):
        from decimal import Decimal, InvalidOperation
        try:
            unit = Decimal(self.chip_unit)
        except (InvalidOperation, TypeError):
            raise ValueError("Chip unit must be a positive decimal amount") from None
        if not unit.is_finite() or unit <= 0 or unit > 1000000:
            raise ValueError("Chip unit must be a positive decimal amount")
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 120:
            raise ValueError("Layout needs a name")
        if type(self.seat_count) is not int or not 2 <= self.seat_count <= 10:
            raise ValueError("Choose between two and ten seats")
        if len(self.reference_size) != 2 or any(type(n) is not int or not 20 <= n <= 16000 for n in self.reference_size):
            raise ValueError("Invalid reference dimensions")
        if self.decimal_separator not in (".", ",") or not 0 < self.small_blind <= self.big_blind:
            raise ValueError("Invalid decimal separator or blinds")
        if type(self.small_blind) is not int or type(self.big_blind) is not int:
            raise ValueError("Blinds must be integer chip units")
        if not math.isfinite(self.threshold) or not .5 <= self.threshold <= 1 or not math.isfinite(self.margin) or not 0 <= self.margin <= .5:
            raise ValueError("Invalid recognition thresholds")
        if type(self.contrast) is not int or not 1 <= self.contrast <= 254:
            raise ValueError("Invalid foreground contrast")
        if len(self.regions) > 150 or len(self.examples) > 2000:
            raise ValueError("Calibration is too large")
        if any(key != region.name for key, region in self.regions.items()):
            raise ValueError("Region name mismatch")
        for example in self.examples:
            if example.kind not in KINDS or not isinstance(example.label, str) or not 1 <= len(example.label) <= 32:
                raise ValueError("Invalid example label")
            if not isinstance(example.group, str) or len(example.group) > 80:
                raise ValueError("Invalid example group")
        return self

    def save(self, path):
        self.validate()
        data = asdict(self)
        data["version"] = 1
        path = Path(path)
        temporary = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 16000000:
            raise ValueError("Layout file is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.pop("version", None) != 1:
            raise ValueError("Unsupported layout version")
        try:
            data["reference_size"] = tuple(data["reference_size"])
            data["regions"] = {key: Region(**{**value, "box": tuple(value["box"])}) for key, value in data["regions"].items()}
            data["examples"] = [Example(**value) for value in data["examples"]]
            layout = cls(**data).validate()
            for example in layout.examples:
                example.image()
            return layout
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid layout file") from exc


def field_choices(seats=6):
    result = [("anchor", "anchor")]
    for prefix, count in (("hole", 2), ("board", 5)):
        for i in range(count):
            result.extend((f"{prefix}{i}.{kind}", kind) for kind in ("rank", "suit"))
    result.append(("pot", "number"))
    for i in range(seats):
        result.extend((f"seat{i}.{suffix}", kind) for suffix, kind in (
            ("stack", "number"), ("bet", "number"), ("status", "status"),
            ("dealer", "flag"), ("actor", "flag"), ("identity", "identity")))
    return tuple(result)
