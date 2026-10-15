"""Reconstruct hand history from observed events, never from game internals."""
from .reader import ReadError


class Tracker:
    def __init__(self):
        self.hand = None
        self.events = []
        self.previous = None
        self.broken = False

    def accept(self, observation):
        if observation.hand != self.hand:
            if self.hand is not None and observation.hand < self.hand:
                raise ReadError("Hand counter moved backwards")
            self.hand = observation.hand
            self.events = []
            self.previous = None
            self.broken = False
        if self.broken:
            raise ReadError("Action history incomplete; start a new hand to resynchronize")
        fresh = []
        try:
            for event in observation.events:
                if event.seq <= len(self.events):
                    if self.events[event.seq - 1] != event:
                        raise ReadError("Previously observed action changed")
                    continue
                if event.seq != len(self.events) + 1:
                    raise ReadError("Missed action; start a new hand to resynchronize")
                self.events.append(event)
                fresh.append(event)
            if self.previous:
                if observation.hole != self.previous.hole or observation.button != self.previous.button:
                    raise ReadError("Cards or button changed within the hand")
                if observation.board[:len(self.previous.board)] != self.previous.board:
                    raise ReadError("Board changed within the hand")
                if "PFTRX".index(observation.street) < "PFTRX".index(self.previous.street):
                    raise ReadError("Street moved backwards")
            if observation.street != "X":
                paid = [sum(e.amount for e in self.events if e.seat == i) for i in range(6)]
                if paid != [s.invested for s in observation.seats]:
                    raise ReadError("Actions do not reconcile with contributions")
                folded = {e.seat for e in self.events if e.action == "F"}
                if folded != {i for i, s in enumerate(observation.seats) if s.status == "F"}:
                    raise ReadError("Folded seats do not reconcile")
            self.previous = observation
            return fresh
        except ReadError:
            self.broken = True
            raise
