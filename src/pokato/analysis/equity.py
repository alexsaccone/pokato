"""Weighted range Monte Carlo, and exact weighted heads-up river enumeration."""
from dataclasses import dataclass
from itertools import combinations
import math
import random
from pokato.core.cards import DECK, evaluate, starting_strength


@dataclass(frozen=True)
class Equity:
    share: float
    standard_error: float
    samples: int
    exact: bool = False


def range_weight(hole, board, events, profile):
    """Heuristic likelihood, not a learned/calibrated opponent policy.

    Each observed call/raise updates the prior using only the board that
    was visible on that street. Positive floors preserve bluff combinations.
    """
    strength = starting_strength(hole)
    threshold = 0.85 - 0.65 * profile.vpip
    weight = 0.12 + 0.88 / (1 + math.exp(-9 * (strength - threshold)))
    for e in events:
        if e.seat != profile.seat or e.action not in "CR":
            continue
        count = {"P": 0, "F": 3, "T": 4, "R": 5}[e.street]
        visible = board[:count]
        if len(visible) >= 3:
            rank = evaluate(list(hole) + list(visible))
            strength = min(0.98, 0.25 + rank[0] * 0.13 + rank[1] / 100)
        power = 2.0 if e.action == "R" else 0.8
        weight *= 0.15 + 0.85 * strength ** power
    return max(0.002, min(1.0, weight))


def draw_hole(rng, deck, board, events, profile):
    # Rejection sampling preserves weighted combinations and card removal.
    for _ in range(2000):
        hole = rng.sample(deck, 2)
        if rng.random() <= range_weight(hole, board, events, profile):
            return hole
    raise ValueError("Range sampling budget exceeded")


def showdown_share(hero, board, opponents):
    own = evaluate(list(hero) + list(board))
    ranks = [own] + [evaluate(list(h) + list(board)) for h in opponents]
    best = max(ranks)
    return 0.0 if own != best else 1 / ranks.count(best)


def equity(hero, board, profiles, events=(), samples=600, seed=1):
    known = list(hero) + list(board)
    remaining = [c for c in DECK if c not in known]
    if len(board) == 5 and len(profiles) == 1:
        numerator = denominator = 0.0
        count = 0
        for hole in combinations(remaining, 2):
            weight = range_weight(hole, board, events, profiles[0])
            numerator += weight * showdown_share(hero, board, [hole])
            denominator += weight
            count += 1
        return Equity(numerator / denominator, 0, count, True)
    if samples < 2 or not profiles:
        raise ValueError("Need opponents and at least two samples")
    rng = random.Random(seed)
    results = []
    for _ in range(samples):
        deck = remaining[:]
        holes = []
        # Shuffle sampling order to avoid systematic priority in multiway pots.
        order = list(profiles)
        rng.shuffle(order)
        for profile in order:
            hole = draw_hole(rng, deck, board, events, profile)
            holes.append(hole)
            deck = [c for c in deck if c not in hole]
        runout = list(board) + rng.sample(deck, 5 - len(board))
        results.append(showdown_share(hero, runout, holes))
    mean = sum(results) / samples
    variance = sum((x - mean) ** 2 for x in results) / (samples - 1)
    return Equity(mean, math.sqrt(variance / samples), samples)
