"""Corroborate visible hole cards without carrying evidence across deals."""
from dataclasses import replace
import time
import numpy as np
from .automatic import center


class HoleCardTracker:
    # Each individual card must be read again within this interval. Holding a
    # glyph is permitted only while its visible shape and location still match.
    MAX_AGE = 12.
    VISUAL_DISTANCE = .12

    def __init__(self):
        self.reset()

    def reset(self):
        self.source = self.timestamp = self.last_update = self.last_result = None
        self.cards = [None, None]
        self.votes = [0, 0]
        self.seen = [None, None]
        self.views = []
        self.board = ()
        self.hero_verified = False
        self.waiting_for_deal = ()

    @staticmethod
    def boxes(pair, size):
        width, height = size or (1., 1.)
        return tuple((c.box[0]/width, c.box[1]/height, c.box[2]/width, c.box[3]/height) for c in pair)

    def view(self, pair, size):
        boxes = self.boxes(pair, size)
        for prior, visuals in self.views:
            matches = True
            for old, new in zip(prior, boxes):
                ox, oy = center(old)
                nx, ny = center(new)
                height = max(old[3]-old[1], new[3]-new[1], 1e-6)
                ratio = (new[2]-new[0])/max(old[2]-old[0], 1e-6)
                if abs(nx-ox) > height*.75 or abs(ny-oy) > height*.75 or not .4 < ratio < 2.5:
                    matches = False
                    break
            if matches:
                return visuals
        return None

    @classmethod
    def same_visual(cls, old, new, *, rank=True, suit=True):
        if not old or len(old) != len(new) or len(old) % 2:
            return False
        before = np.frombuffer(old, dtype=np.uint8).astype(float).reshape(2, -1)
        after = np.frombuffer(new, dtype=np.uint8).astype(float).reshape(2, -1)
        # Compare uncertain glyphs separately and weight their foreground. An
        # unchanged rank must not hide a changed suit in a whole-card average.
        differences = np.abs(before-after).sum(axis=1)/np.maximum(np.maximum(before, after).sum(axis=1), 1.)
        return all(differences[index] <= cls.VISUAL_DISTANCE
                   for index, uncertain in enumerate((rank, suit)) if uncertain)

    def remember(self, pair, size):
        boxes = self.boxes(pair, size)
        # Replace rather than accumulate slight movements of the same view.
        prior = self.view(pair, size)
        if prior is not None:
            self.views = [v for v in self.views if v[1] is not prior]
        self.views.append((boxes, tuple(c.visual if c.value or prior is None else prior[index]
                                        for index, c in enumerate(pair))))
        self.views = self.views[-4:]

    @staticmethod
    def conflicts(old, new):
        return old is not None and ((old.rank and new.rank and old.rank != new.rank) or
                                    (old.suit and new.suit and old.suit != new.suit))

    def result(self, reading, hand, status, held=False):
        self.last_result = replace(reading, hand=tuple(hand), hero_verified=self.hero_verified and bool(hand),
                                   hand_status=status, hand_held=held)
        return self.last_result

    def update(self, reading, now=None):
        now = time.monotonic() if now is None else now
        if (reading.source != self.source or
                (self.last_update is not None and now-self.last_update > self.MAX_AGE) or
                (self.timestamp is not None and reading.timestamp < self.timestamp)):
            self.reset()
        if not reading.table_found or len(reading.hand) != 2:
            self.reset()
            self.source, self.timestamp, self.last_update = reading.source, reading.timestamp, now
            return self.result(reading, (), 'Hole cards cleared · waiting for visible cards')
        if self.timestamp == reading.timestamp and self.last_result is not None:
            # Re-delivering one captured frame is not independent evidence.
            return self.last_result

        pair = reading.hand
        current_board = tuple(c.value for c in reading.board)
        retreat = len(current_board) < len(self.board)
        board_changed = any(old and new and old != new for old, new in zip(self.board, current_board))
        reset_reason = ''
        if retreat or board_changed:
            old_pair = tuple(c.value if c else None for c in self.cards)
            self.reset()
            self.waiting_for_deal = old_pair if any(old_pair) else ()
            reset_reason = 'New hand · confirming hole cards'
        self.source, self.timestamp, self.last_update = reading.source, reading.timestamp, now
        self.board = current_board

        if self.waiting_for_deal:
            changed = any(value and ((card.rank and card.rank != value[0]) or
                                    (card.suit and card.suit != value[1]))
                          for value, card in zip(self.waiting_for_deal, pair))
            # Board disappearance may precede removal of the old hole-card
            # graphics. Do not immediately reconfirm that lingering old pair.
            if not changed and len(current_board) < 3:
                return self.result(reading, (), 'New hand · waiting for new hole cards')
            self.waiting_for_deal = ()

        visuals = self.view(pair, reading.image_size)
        conflict = any(self.conflicts(old, new) for old, new in zip(self.cards, pair))
        expired = any(card.value is None and seen is not None and now-seen > self.MAX_AGE
                      for card, seen in zip(pair, self.seen))
        unseen_view = bool(self.views) and visuals is None and not all(c.value for c in pair)
        changed_ink = visuals is not None and any(
            c.value is None and not self.same_visual(old, c.visual, rank=not c.rank, suit=not c.suit)
            for old, c in zip(visuals, pair))
        if conflict or expired or unseen_view or changed_ink:
            self.reset()
            self.source, self.timestamp, self.last_update = reading.source, reading.timestamp, now
            self.board = current_board
            reset_reason = 'Hole cards changed · confirming new readings'

        values = tuple(c.value for c in pair)
        duplicates = [view for view in reading.hand_views if view != pair and
                      tuple(c.value for c in view) == values and all(values) and
                      tuple(c.box for c in view) != tuple(c.box for c in pair)]
        votes = 2 if duplicates else 1
        for index, card in enumerate(pair):
            if card.value:
                self.cards[index] = card
                self.votes[index] = min(2, self.votes[index]+votes)
                self.seen[index] = now
        self.hero_verified = self.hero_verified or reading.hero_verified
        self.remember(pair, reading.image_size)
        for view in duplicates:
            self.remember(view, reading.image_size)

        hand = []
        held = False
        for index, card in enumerate(pair):
            if self.votes[index] >= 2:
                hand.append(replace(self.cards[index], box=card.box))
                held = held or card.value is None
            else:
                hand.append(replace(card, rank=None, suit=None, score=0.))
        known = [card.value for card in (*reading.board, *hand) if card.value]
        if len(known) != len(set(known)):
            self.reset()
            return self.result(reading, (), 'Conflicting cards · hole cards cleared')
        oldest = max((now-seen for seen in self.seen if seen is not None), default=0.)
        status = (f'Hole cards held · last read {oldest:.0f}s ago' if held else
                  'Hole cards confirmed' if all(c.value for c in hand) else
                  reset_reason or 'Confirming hole cards')
        return self.result(reading, hand, status, held)
