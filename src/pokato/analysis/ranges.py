"""Explicit weighted ranges. Weights are relative combination frequencies."""
from bisect import bisect_right
from dataclasses import dataclass
from itertools import combinations
import math
import re
from pokato.core.cards import DECK, RANKS, validate_cards


def combo_key(cards):
    validate_cards(cards)
    if len(cards) != 2:
        raise ValueError("A combination needs two cards")
    return tuple(sorted(cards, key=DECK.index))


def class_name(a, b):
    ra, rb = sorted((a[0], b[0]), key=RANKS.index, reverse=True)
    return ra + rb + ("" if ra == rb else "s" if a[1] == b[1] else "o")


@dataclass(frozen=True)
class ComboRange:
    weights: tuple

    def available(self, known):
        blocked = set(known)
        return [(hole, weight) for hole, weight in self.weights if not blocked.intersection(hole)]


def parse_range(expression):
    """AA, QQ+, ATs+, AKo, AsKh:0.5, or * (all hands). Last token wins."""
    values = {}
    for token in re.split(r"[,;\s]+", expression.strip()):
        if not token:
            continue
        name, separator, raw_weight = token.partition(":")
        try:
            weight = float(raw_weight) if separator else 1.0
        except ValueError as exc:
            raise ValueError(f"Invalid weight in {token}") from exc
        if not math.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError("Range weights must be finite numbers from 0 to 1")
        if len(name) == 4 and name[:2] in DECK and name[2:] in DECK:
            holes = [combo_key((name[:2], name[2:]))]
        elif name == "*":
            holes = list(combinations(DECK, 2))
        else:
            match = re.fullmatch(r"([2-9TJQKA])([2-9TJQKA])([so]?)(\+?)", name)
            if not match:
                raise ValueError(f"Unknown range token: {name}")
            a, b, suited, plus = match.groups()
            if RANKS.index(a) < RANKS.index(b) or (a == b and suited):
                raise ValueError(f"Use high rank first and no suit suffix for pairs: {name}")
            if a == b:
                names = {r + r for r in (RANKS[RANKS.index(a):] if plus else a)}
            else:
                seconds = RANKS[RANKS.index(b):RANKS.index(a)] if plus else b
                names = {a + r + suffix for r in seconds for suffix in (suited if suited else "so")}
            holes = [hole for hole in combinations(DECK, 2) if class_name(*hole) in names]
        for hole in holes:
            values[hole] = weight
    weights = tuple((hole, weight) for hole, weight in values.items() if weight > 0)
    if not weights:
        raise ValueError("Range has no positive-weight combinations")
    return ComboRange(weights)


class Distribution:
    def __init__(self, values):
        self.holes, self.cumulative = [], []
        total = 0.0
        for hole, weight in values:
            if weight > 0:
                total += weight
                self.holes.append(tuple(hole))
                self.cumulative.append(total)
        if not total:
            raise ValueError("Range is empty after removing known cards")
        self.total = total

    def sample(self, rng):
        return self.holes[bisect_right(self.cumulative, rng.random() * self.total)]


def joint_holes(rng, distributions):
    """Independent weighted combinations conditioned on no shared cards.

    Whole-deal rejection, rather than sequential renormalization, preserves
    the product-of-ranges posterior under card removal.
    """
    for _ in range(10000):
        holes = [distribution.sample(rng) for distribution in distributions]
        cards = [card for hole in holes for card in hole]
        if len(set(cards)) == len(cards):
            return holes
    raise ValueError("Opponent ranges conflict or overlap too heavily; widen the ranges")
