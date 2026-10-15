"""Integer-chip NLHE with full raises, short all-ins, uncalled refunds and side pots."""
from dataclasses import dataclass, field
import random
from .cards import DECK, evaluate

STREETS = "PFTRX"  # preflop, flop, turn, river, complete


@dataclass
class Player:
    name: str
    stack: int = 1000
    hole: list = field(default_factory=list)
    bet: int = 0
    invested: int = 0
    folded: bool = False


@dataclass(frozen=True)
class Event:
    seq: int
    seat: int
    street: str
    action: str  # B blind, F fold, K check, C call, R raise-to
    amount: int  # additional chips paid, including for raises


class Game:
    small_blind = 5
    big_blind = 10

    def __init__(self, seed=7, stacks=None):
        self.rng = random.Random(seed)
        names = ["YOU", "Juniper", "Atlas", "Marlow", "Cedar", "Nova"]
        self.players = [Player(name, stack) for name, stack in
                        zip(names, stacks if stacks is not None else [1000] * 6)]
        if len(self.players) != 6 or any(p.stack <= 0 for p in self.players):
            raise ValueError("Six positive stacks required")
        self.hand_id = 0
        self.button = 5
        self.events = []
        self.board = []
        self.street = "X"
        self.actor = -1
        self.result = ""

    @property
    def pot(self):
        return sum(p.invested for p in self.players)

    def _pay(self, seat, amount):
        p = self.players[seat]
        paid = min(p.stack, amount)
        p.stack -= paid
        p.bet += paid
        p.invested += paid
        return paid

    def _record(self, seat, action, amount):
        self.events.append(Event(len(self.events) + 1, seat, self.street, action, amount))

    def new_hand(self):
        if self.street != "X":
            raise ValueError("Finish the current hand first")
        self.hand_id += 1
        self.button = (self.button + 1) % 6
        self.deck = list(DECK)
        self.rng.shuffle(self.deck)
        self.board, self.events, self.result = [], [], ""
        self.street = "P"
        for p in self.players:
            # A practice table auto-rebuys busted seats between hands.
            if not p.stack:
                p.stack = 1000
            p.hole = [self.deck.pop(), self.deck.pop()]
            p.bet = p.invested = 0
            p.folded = False
        for offset, amount in ((1, self.small_blind), (2, self.big_blind)):
            seat = (self.button + offset) % 6
            self._record(seat, "B", self._pay(seat, amount))
        self.current_bet = self.big_blind
        self.last_raise = self.big_blind
        self.acted_at = {}
        self.pending = {i for i, p in enumerate(self.players) if p.stack}
        self._advance((self.button + 2) % 6)

    def legal(self):
        if self.actor < 0:
            return {}
        p = self.players[self.actor]
        cost = min(p.stack, max(0, self.current_bet - p.bet))
        # Cumulative short raises reopen betting after a full increment.
        reopened = (self.actor not in self.acted_at or
                    self.current_bet - self.acted_at[self.actor] >= self.last_raise)
        ceiling = p.bet + p.stack
        others = any(i != self.actor and not q.folded and q.stack
                     for i, q in enumerate(self.players))
        can_raise = reopened and ceiling > self.current_bet and others
        return {"call": cost, "check": cost == 0,
                "min_raise": min(ceiling, self.current_bet + self.last_raise) if can_raise else 0,
                "max_raise": ceiling if can_raise else 0}

    def act(self, action, raise_to=0):
        if self.actor < 0:
            raise ValueError("No action pending")
        seat = self.actor
        p = self.players[seat]
        legal = self.legal()
        if action == "F":
            p.folded = True
            paid = 0
        elif action == "K" and legal["check"]:
            paid = 0
        elif action == "C" and not legal["check"]:
            paid = self._pay(seat, legal["call"])
        elif action == "R" and legal["min_raise"] and legal["min_raise"] <= raise_to <= legal["max_raise"]:
            increment = raise_to - self.current_bet
            paid = self._pay(seat, raise_to - p.bet)
            self.current_bet = raise_to
            if increment >= self.last_raise:
                self.last_raise = increment
            self.pending.update(i for i, q in enumerate(self.players)
                                if i != seat and not q.folded and q.stack and q.bet < self.current_bet)
        else:
            raise ValueError("Illegal action or raise size")
        self.acted_at[seat] = self.current_bet
        self.pending.discard(seat)
        self._record(seat, action, paid)
        self._advance(seat)

    def _advance(self, previous):
        live = [i for i, p in enumerate(self.players) if not p.folded]
        if len(live) == 1:
            self._settle()
            return
        self.pending = {i for i in self.pending if not self.players[i].folded and self.players[i].stack}
        able = [i for i in live if self.players[i].stack]
        if len(able) <= 1:
            self.pending = {i for i in self.pending if self.players[i].bet < self.current_bet}
        if self.pending:
            self.actor = next((previous + n) % 6 for n in range(1, 7)
                              if (previous + n) % 6 in self.pending)
            return
        if self.street == "R":
            self._settle()
            return
        self.street = STREETS[STREETS.index(self.street) + 1]
        self.deck.pop()  # burn
        self.board.extend(self.deck.pop() for _ in range(3 if self.street == "F" else 1))
        for p in self.players:
            p.bet = 0
        self.current_bet = 0
        self.last_raise = self.big_blind
        self.acted_at = {}
        self.pending = set(able) if len(able) > 1 else set()
        self._advance(self.button)

    def _settle(self):
        contributions = sorted(set(p.invested for p in self.players if p.invested))
        awards = [0] * 6
        previous = 0
        ranks = {i: evaluate(p.hole + self.board) for i, p in enumerate(self.players)
                 if not p.folded} if len(self.board) == 5 else {}
        for level in contributions:
            participants = [i for i, p in enumerate(self.players) if p.invested >= level]
            amount = (level - previous) * len(participants)
            eligible = [i for i in participants if not self.players[i].folded]
            if len(participants) == 1:  # uncalled portion
                winners = participants
            elif len(eligible) == 1:
                winners = eligible
            else:
                best = max(ranks[i] for i in eligible)
                winners = [i for i in eligible if ranks[i] == best]
            # Odd chips go clockwise from the button.
            winners.sort(key=lambda i: (i - self.button - 1) % 6)
            for n, seat in enumerate(winners):
                awards[seat] += amount // len(winners) + (n < amount % len(winners))
            previous = level
        self.result = " / ".join(f"{p.name} +{awards[i]}" for i, p in enumerate(self.players) if awards[i])
        for i, p in enumerate(self.players):
            p.stack += awards[i]
            p.invested = p.bet = 0
        self.street = "X"
        self.actor = -1
