from dataclasses import dataclass
from PIL import Image, ImageChops, ImageStat
from pokato.core.cards import DECK, validate_cards
from pokato.core.game import Event
from pokato.simulator.layout import FIELDS, CELL_W, CELL_H, WIDTH, HEIGHT, ALPHABET, glyph


class ReadError(ValueError):
    pass


@dataclass(frozen=True)
class Seat:
    status: str
    stack: int
    bet: int
    invested: int


@dataclass(frozen=True)
class Observation:
    hand: int
    street: str
    actor: int
    button: int
    pot: int
    call: int
    minimum: int
    maximum: int
    hole: tuple
    board: tuple
    seats: tuple
    events: tuple
    confidence: float


class Reader:
    """Fixed-layout glyph recognition for our own V1 practice table.

    Not general OCR. Unfamiliar fonts, distorted video, occlusion, or corrupt
    fields fail closed. The numeric confidence measures template similarity,
    not a calibrated probability of correctness.
    """
    def __init__(self):
        self.templates = {c: glyph(c).convert("RGB") for c in ALPHABET}
        self.exact = {im.tobytes(): c for c, im in self.templates.items()}

    def read(self, frame):
        size = frame.size
        if size[0] < WIDTH or size[1] < HEIGHT or abs(size[0] / WIDTH - size[1] / HEIGHT) > 0.003:
            raise ReadError("Unsupported table size or aspect ratio")
        frame = frame.convert("RGB")
        if size != (WIDTH, HEIGHT):
            frame = frame.resize((WIDTH, HEIGHT), Image.Resampling.NEAREST)
        confidence = 1.0
        values = {}
        for key, field in FIELDS.items():
            chars = []
            for n in range(field.length):
                x = field.x + n * CELL_W
                crop = frame.crop((x, field.y, x + CELL_W, field.y + CELL_H))
                char = self.exact.get(crop.tobytes())
                if char is None:
                    scores = sorted((sum(ImageStat.Stat(ImageChops.difference(crop, template)).mean) / (3 * 255), c)
                                    for c, template in self.templates.items())
                    error, char = scores[0]
                    if error > 0.008 or scores[1][0] - error < 0.008:
                        raise ReadError(f"Unreadable {key}; restore a clear, undistorted table")
                    confidence = min(confidence, 1 - error)
                chars.append(char)
            values[key] = "".join(chars).strip()
        try:
            if values["marker"] != "POKATO-V1":
                raise ValueError("Practice-table marker missing")
            street = values["street"]
            if street not in ("P", "F", "T", "R", "X"):
                raise ValueError("Invalid street")
            actor = -1 if values["actor"] == "X" else int(values["actor"])
            button = int(values["button"])
            if not -1 <= actor < 6 or not 0 <= button < 6 or (street == "X") != (actor == -1):
                raise ValueError("Invalid actor or button")
            seats = tuple(Seat(values[f"status{i}"], *(int(values[f"{key}{i}"])
                                                      for key in ("stack", "bet", "invested"))) for i in range(6))
            if any(s.status not in ("A", "F", "I") or s.bet > s.invested for s in seats):
                raise ValueError("Invalid seat")
            if any(s.status == "I" and s.stack != 0 for s in seats):
                raise ValueError("Invalid all-in indicator")
            if actor >= 0 and (seats[actor].status != "A" or seats[actor].stack == 0):
                raise ValueError("Invalid active seat")
            hole = tuple(values[f"hole{i}"] for i in range(2))
            raw_board = [values[f"board{i}"] for i in range(5)]
            board = tuple(c for c in raw_board if c != "--")
            if raw_board != list(board) + ["--"] * (5 - len(board)):
                raise ValueError("Non-contiguous board")
            validate_cards(hole + board)
            expected = {"P": 0, "F": 3, "T": 4, "R": 5}
            if street in expected and len(board) != expected[street]:
                raise ValueError("Board/street mismatch")
            numbers = {key: int(values[key]) for key in ("hand", "pot", "call", "minimum", "maximum")}
            if any(n < 0 for n in numbers.values()) or any(min(s.stack, s.bet, s.invested) < 0 for s in seats):
                raise ValueError("Negative chips")
            if numbers["pot"] != sum(s.invested for s in seats):
                raise ValueError("Pot accounting mismatch")
            if actor >= 0:
                cost = min(seats[actor].stack, max(s.bet for s in seats) - seats[actor].bet)
                # A short big blind can leave the nominal preflop price at 10.
                if street == "P":
                    cost = min(seats[actor].stack, max(10, max(s.bet for s in seats)) - seats[actor].bet)
                if cost != numbers["call"]:
                    raise ValueError("Call cost mismatch")
                if not 0 <= numbers["minimum"] <= numbers["maximum"] <= seats[actor].stack + seats[actor].bet:
                    raise ValueError("Invalid raise limits")
            events = []
            for i in range(8):
                if not values[f"event{i}"]:
                    continue
                seq, seat, st, action, amount = values[f"event{i}"].split()
                event = Event(int(seq), int(seat), st, action, int(amount))
                if not 0 <= event.seat < 6 or st not in "PFTR" or action not in "BFKCR" or event.amount < 0:
                    raise ValueError("Invalid event")
                if action in "FK" and event.amount:
                    raise ValueError("Fold/check paid chips")
                events.append(event)
            if any(b.seq != a.seq + 1 for a, b in zip(events, events[1:])):
                raise ValueError("Non-contiguous tape")
            return Observation(**numbers, street=street, actor=actor, button=button,
                               hole=hole, board=board, seats=seats, events=tuple(events), confidence=confidence)
        except (ValueError, KeyError) as exc:
            raise ReadError(str(exc)) from exc
