"""Independent synthetic skins for reader QA/demo, never a recognition shortcut."""
from decimal import Decimal
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pokato.core.cards import SUIT_SYMBOLS
from pokato.core.game import Game
from .calibrated import CalibratedReader, TableSnapshot, TableSeat
from .layouts import Layout, Region, Example


class SyntheticSkin:
    def __init__(self, style="wide"):
        self.style = style
        self.size = (1200, 760) if style == "wide" else (1000, 900)
        self.background = "#0c5147" if style == "wide" else "#29243f"
        self.font_path = next((p for p in (
            "C:/Windows/Fonts/consola.ttf" if style == "wide" else "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf") if Path(p).exists()), None)
        self.font = ImageFont.truetype(self.font_path, 22) if self.font_path else ImageFont.load_default(size=22)
        self.layout = Layout(name=f"Synthetic {style} demo", reference_size=self.size, chip_unit="0.01")
        self.boxes = {}
        self.add("anchor", (20, 16, 220, 55), "anchor")
        for prefix, count, start in (("hole", 2, 30), ("board", 5, 300 if style == "wide" else 270)):
            for i in range(count):
                x = start+i*(78 if prefix == "hole" else 130)
                self.add(f"{prefix}{i}.rank", (x, 95, x+33, 133), "rank")
                self.add(f"{prefix}{i}.suit", (x+35, 95, x+68, 133), "suit")
        self.add("pot", (400, 190, 620, 230), "number")
        for i in range(6):
            y = (280 if style == "wide" else 320)+i*(70 if style == "wide" else 80)
            self.add(f"seat{i}.identity", (30, y, 160, y+36), "identity")
            self.add(f"seat{i}.stack", (180, y, 390, y+36), "number")
            self.add(f"seat{i}.bet", (410, y, 620, y+36), "number")
            self.add(f"seat{i}.status", (640, y, 690, y+36), "status")
            self.add(f"seat{i}.dealer", (740, y, 772, y+32), "flag")
            self.add(f"seat{i}.actor", (820, y, 852, y+32), "flag")

    def add(self, name, box, kind):
        self.boxes[name] = box
        w, h = self.size
        self.layout.regions[name] = Region(name, (box[0]/w, box[1]/h, box[2]/w, box[3]/h), kind)

    def tile(self, name, label):
        region = self.layout.regions[name]
        box = self.boxes[name]
        size = box[2]-box[0], box[3]-box[1]
        image = Image.new("RGB", size, "#f7f5ef" if region.kind in ("rank", "suit") else "#182535")
        draw = ImageDraw.Draw(image)
        if region.kind == "flag":
            draw.ellipse((4, 4, size[0]-4, size[1]-4), fill="#ffd65a" if label == "yes" else "#304156")
        elif region.kind == "status":
            draw.rectangle((0, 0, *size), fill={"A": "#215d87", "F": "#666666", "I": "#b26820"}[label])
            draw.text((10, 2), label, font=self.font, fill="white")
        elif label != "empty":
            text = SUIT_SYMBOLS.get(label, label) if region.kind == "suit" else label
            draw.text((4, 2), text, font=self.font,
                      fill="#182535" if region.kind in ("rank", "suit") else "#f7f5ef")
        return image

    def amount(self, value):
        return f"${Decimal(value)*Decimal(self.layout.chip_unit):,.2f}"

    def render(self, snapshot):
        image = Image.new("RGB", self.size, self.background)
        draw = ImageDraw.Draw(image)
        draw.text((30, 62), "YOUR CARDS                 COMMUNITY CARDS", font=self.font, fill="white")
        draw.text((180, 245), "STACK             BET             STATUS   DEALER  ACTOR", font=self.font, fill="white")
        for name, region in self.layout.regions.items():
            if name == "anchor":
                label = "FELT CLUB" if self.style == "wide" else "NIGHT TABLE"
            elif name == "pot":
                label = self.amount(snapshot.pot)
            elif name.startswith(("hole", "board")):
                prefix, kind = name.split(".")
                cards = snapshot.hole if prefix.startswith("hole") else snapshot.board
                i = int(prefix[-1])
                label = (cards[i][0] if kind == "rank" else cards[i][1]) if i < len(cards) else "empty"
            else:
                seat_name, kind = name.split(".")
                i = int(seat_name[4:])
                seat = snapshot.seats[i]
                label = self.amount(getattr(seat, kind)) if kind in ("stack", "bet") else (
                    "yes" if i == getattr(snapshot, "button" if kind == "dealer" else "actor") else "no") if kind in ("dealer", "actor") else (
                    seat.status if kind == "status" else f"Player {i}")
            image.paste(self.tile(name, label), self.boxes[name][:2])
        return image

    def train(self):
        layout = self.layout
        for name, region in layout.regions.items():
            if region.kind == "identity":
                continue
            if region.kind in ("rank", "suit", "number") and any(e.kind == region.kind for e in layout.examples):
                continue
            if region.kind == "rank":
                labels = tuple("23456789TJQKA")+("empty",)
            elif region.kind == "suit":
                labels = tuple("cdhs")+("empty",)
            elif region.kind == "number":
                labels = ("0123456789.,$KM",)
            elif region.kind == "status":
                labels = tuple("AFI")
            elif region.kind == "anchor":
                labels = ("FELT CLUB" if self.style == "wide" else "NIGHT TABLE",)
            else:
                labels = ("yes", "no")
            for label in labels:
                crop = self.tile(name, label)
                # The long amount alphabet is a separate annotated font sample.
                if region.kind == "number":
                    crop = Image.new("RGB", (250, 40), "#182535")
                    ImageDraw.Draw(crop).text((4, 2), label, font=self.font, fill="#f7f5ef")
                value = "match" if region.kind == "anchor" else label
                example = Example.create(region, value, crop)
                from .calibrated import compiled
                compiled(example, layout.contrast)
                layout.examples.append(example)
        return layout


def from_game(game, index):
    return TableSnapshot(index, index*.25, tuple(game.players[0].hole), tuple(game.board), game.pot,
                         tuple(TableSeat("F" if p.folded else "I" if not p.stack else "A", p.stack, p.bet)
                               for p in game.players), game.button, game.actor, game.street, 1.)


def demo_frames(style="wide"):
    skin = SyntheticSkin(style)
    layout = skin.train()
    game = Game()
    game.new_hand()
    result = []
    while game.street != "X":
        snapshot = from_game(game, len(result))
        result.append((skin.render(snapshot), snapshot))
        game.act("K" if game.legal()["check"] else "C")
    return layout, result
