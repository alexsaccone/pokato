"""Conservative action inference from visible table snapshots, without a tape.

Reconciled means consistent with captured frames, not proof that unseen actions
did not occur. This reader milestone does not enable external recommendations.
"""
from dataclasses import dataclass
from pokato.core.game import Event
from .reader import Observation, Seat


@dataclass(frozen=True)
class HistoryResult:
    quality: str
    message: str
    events: tuple = ()
    observation: object = None


class TableHistory:
    def __init__(self, layout, stable_frames=2):
        self.layout, self.required = layout, stable_frames
        self.previous = None
        self.events = []
        self.hand = 0
        self.broken = False
        self.signature = None
        self.repeats = 0
        self.last_index = None
        self.pending = set()
        self.acted = {}
        self.price = 0
        self.last_raise = layout.big_blind

    def next_seat(self, previous, candidates):
        return next((i for step in range(1, self.layout.seat_count+1)
                     if (i := (previous+step) % self.layout.seat_count) in candidates), -1)

    def fail(self, message):
        self.broken = True
        return HistoryResult("gap", message+"; wait for the next observed blind-only deal", tuple(self.events))

    def result(self, snapshot):
        observation = None
        if len(snapshot.seats) == 6 and snapshot.actor >= 0:
            actor = snapshot.actor
            own = snapshot.seats[actor]
            cost = min(own.stack, max(0, self.price-own.bet))
            reopened = actor not in self.acted or self.price-self.acted[actor] >= self.last_raise
            others = any(i != actor and s.status == "A" and s.stack for i, s in enumerate(snapshot.seats))
            ceiling = own.bet+own.stack
            can_raise = reopened and others and ceiling > self.price
            minimum = min(ceiling, self.price+self.last_raise) if can_raise else 0
            observation = Observation(self.hand, snapshot.street, snapshot.actor, snapshot.button, snapshot.pot,
                                      cost, minimum, ceiling if can_raise else 0, snapshot.hole, snapshot.board,
                                      tuple(Seat(s.status, s.stack, s.bet, self.invested[i]) for i, s in enumerate(snapshot.seats)),
                                      tuple(self.events), snapshot.score)
        return HistoryResult("reconciled", "Visible actions and chips reconcile; external recommendations remain withheld",
                             tuple(self.events), observation)

    def start(self, snapshot):
        if snapshot.street != "P" or len(snapshot.hole) != 2:
            return HistoryResult("unverified", "Start capture before the first voluntary preflop action")
        live = {i for i, seat in enumerate(snapshot.seats) if seat.status != "F"}
        if len(live) < 2 or snapshot.button not in live:
            return HistoryResult("unverified", "Blind-only start requires an occupied dealer and at least two players")
        sb = snapshot.button if len(live) == 2 else self.next_seat(snapshot.button, live)
        bb = self.next_seat(sb, live)
        expected = [0]*len(snapshot.seats)
        expected[sb] = min(self.layout.small_blind, snapshot.seats[sb].stack+snapshot.seats[sb].bet)
        expected[bb] = min(self.layout.big_blind, snapshot.seats[bb].stack+snapshot.seats[bb].bet)
        if expected != [s.bet for s in snapshot.seats] or snapshot.pot != sum(expected):
            return HistoryResult("unverified", "Blind-only start not observed; check blinds, pot convention and chip unit")
        pending = {i for i in live if snapshot.seats[i].stack}
        actor = self.next_seat(bb, pending)
        if snapshot.actor != actor:
            return HistoryResult("unverified", "Starting actor does not match blind order")
        self.hand += 1
        self.events = [Event(1, sb, "P", "B", expected[sb]), Event(2, bb, "P", "B", expected[bb])]
        self.initial = [s.stack+s.bet for s in snapshot.seats]
        self.invested = list(expected)
        self.pending, self.acted = pending, {}
        self.price = self.last_raise = self.layout.big_blind
        self.previous, self.broken = snapshot, False
        return self.result(snapshot)

    def accept(self, reading):
        snapshot = reading.snapshot
        if snapshot is None:
            self.signature, self.repeats = None, 0
            return HistoryResult("unreadable", "; ".join(reading.issues[:3]), tuple(self.events))
        if snapshot.manual:
            return self.fail("Manual corrections are provisional and cannot establish automatic action history")
        if snapshot.approximate:
            self.signature, self.repeats = None, 0
            return self.fail("Abbreviated K/M amounts may be rounded and cannot establish exact chip history")
        signature = (snapshot.hole, snapshot.board, snapshot.pot, snapshot.seats, snapshot.button, snapshot.actor, snapshot.street)
        if signature != self.signature:
            self.signature, self.repeats = signature, 1
        elif snapshot.index != self.last_index:
            self.repeats += 1
        self.last_index = snapshot.index
        if self.repeats < self.required:
            return HistoryResult("waiting", "Waiting for consecutive matching readings", tuple(self.events))
        if snapshot.street == "X":
            self.previous = None
            return HistoryResult("ended", "Between hands; settlement is not inferred", tuple(self.events))
        previous = self.previous
        new_hand = previous is None or (snapshot.street == "P" and (
            snapshot.hole != previous.hole or snapshot.button != previous.button or previous.street != "P"))
        if new_hand:
            return self.start(snapshot)
        if self.broken:
            return HistoryResult("gap", "History remains incomplete; wait for a fresh blind-only deal", tuple(self.events))
        if snapshot.hole != previous.hole or snapshot.button != previous.button:
            return self.fail("Cards or dealer changed within a hand")
        if snapshot.board[:len(previous.board)] != previous.board:
            return self.fail("Previously observed board cards changed")
        if any(a.identity and b.identity and a.identity != b.identity for a, b in zip(previous.seats, snapshot.seats)):
            return self.fail("A seat identity changed")
        if snapshot.timestamp < previous.timestamp or snapshot.index < previous.index:
            return self.fail("Frame order moved backwards")
        before_street, after_street = "PFTR".index(previous.street), "PFTR".index(snapshot.street)
        ending = after_street > before_street
        if after_street < before_street:
            return self.fail("Street moved backwards without an observed new deal")
        unchanged = (snapshot.board, snapshot.pot, snapshot.seats, snapshot.actor) == (
            previous.board, previous.pot, previous.seats, previous.actor)
        if unchanged:
            self.previous = snapshot
            return self.result(snapshot)
        if previous.actor < 0:
            return self.fail("No previous actor available to infer a decision")
        actor = previous.actor
        changed = [i for i, (a, b) in enumerate(zip(previous.seats, snapshot.seats))
                   if a.stack != b.stack or a.status != b.status or (not ending and a.bet != b.bet)]
        if any(i != actor for i in changed):
            return self.fail("Multiple or out-of-order player changes occurred between frames")
        old, new = previous.seats[actor], snapshot.seats[actor]
        amount = old.stack-new.stack
        if amount < 0:
            return self.fail("Stack increased before a visible settlement")
        target = old.bet+amount
        if not ending and new.bet != target:
            return self.fail("Stack change does not match the visible bet change")
        owed = max(0, self.price-old.bet)
        if new.status == "F" and old.status != "F":
            if amount:
                return self.fail("Payment and fold were both missed")
            action = "F"
        elif amount:
            if target > self.price:
                reopened = actor not in self.acted or self.price-self.acted[actor] >= self.last_raise
                if not reopened or (target-self.price < self.last_raise and new.stack):
                    return self.fail("Inferred raise violates reopening or minimum-size rules")
                if not any(i != actor and s.status == "A" and s.stack for i, s in enumerate(previous.seats)):
                    return self.fail("Cannot bet into an all-in-only field")
                action = "R"
            else:
                if amount != min(old.stack, owed):
                    return self.fail("Inferred call does not match the price")
                action = "C"
        else:
            if owed:
                return self.fail("Actor moved on without a visible call or fold")
            if not ending and snapshot.actor == actor:
                return self.fail("Visible state changed without an attributable action")
            action = "K"
        pending, acted, invested = set(self.pending), dict(self.acted), list(self.invested)
        price, last = self.price, self.last_raise
        if action == "R":
            if target-price >= last:
                last = target-price
            price = target
            pending.update(i for i, seat in enumerate(snapshot.seats) if i != actor and seat.status == "A" and seat.stack)
        acted[actor] = price
        pending.discard(actor)
        pending = {i for i in pending if snapshot.seats[i].status == "A" and snapshot.seats[i].stack}
        if sum(s.status == "A" and s.stack > 0 for s in snapshot.seats) <= 1:
            pending = {i for i in pending if (previous.seats[i].bet if ending else snapshot.seats[i].bet) < price}
        invested[actor] += amount
        if snapshot.pot != sum(invested) or any(self.initial[i]-s.stack != invested[i] for i, s in enumerate(snapshot.seats)):
            return self.fail("Chip totals do not reconcile; rake, missed actions or a read error may be present")
        if ending:
            able = {i for i, s in enumerate(snapshot.seats) if s.status == "A" and s.stack}
            if pending or (after_street != before_street+1 and len(able) > 1):
                return self.fail("Actions or streets were skipped before the board transition")
            if any(s.bet for s in snapshot.seats):
                return self.fail("New-street bets already present; an action was missed")
            pending = able if len(able) > 1 else set()
            expected_actor = self.next_seat(snapshot.button, pending)
            price, last, acted = 0, self.layout.big_blind, {}
        else:
            expected_actor = self.next_seat(actor, pending)
        if snapshot.actor != expected_actor:
            return self.fail("Acting player does not match inferred betting order")
        self.events.append(Event(len(self.events)+1, actor, previous.street, action, amount))
        self.pending, self.acted, self.invested = pending, acted, invested
        self.price, self.last_raise, self.previous = price, last, snapshot
        return self.result(snapshot)
