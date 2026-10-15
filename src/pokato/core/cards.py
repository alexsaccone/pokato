"""Cards are two-character strings, e.g. As, Td, 2c."""
from collections import Counter

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(r + s for r in RANKS for s in SUITS)
CATEGORIES = ("High card", "Pair", "Two pair", "Three of a kind", "Straight",
              "Flush", "Full house", "Four of a kind", "Straight flush")


def validate_cards(cards):
    if len(set(cards)) != len(cards) or any(c not in DECK for c in cards):
        raise ValueError("Invalid or duplicated cards")


def straight_high(ranks):
    values = set(ranks)
    if 14 in values:
        values.add(1)
    return next((high for high in range(14, 4, -1)
                 if all(high - n in values for n in range(5))), 0)


def evaluate(cards):
    """Best five-card rank from 5–7 cards. Higher tuples win; suits never break ties."""
    validate_cards(cards)
    if not 5 <= len(cards) <= 7:
        raise ValueError("Evaluation needs five to seven cards")
    ranks = [RANKS.index(c[0]) + 2 for c in cards]
    counts = Counter(ranks)
    groups = sorted(((n, r) for r, n in counts.items()), reverse=True)
    flush = next(([RANKS.index(c[0]) + 2 for c in cards if c[1] == s]
                  for s in SUITS if sum(c[1] == s for c in cards) >= 5), [])
    if flush and straight_high(flush):
        return (8, straight_high(flush))
    if groups[0][0] == 4:
        quad = groups[0][1]
        return (7, quad, max(r for r in ranks if r != quad))
    trips = sorted((r for r, n in counts.items() if n >= 3), reverse=True)
    if trips:
        pairs = sorted((r for r, n in counts.items() if n >= 2 and r != trips[0]), reverse=True)
        if pairs:
            return (6, trips[0], pairs[0])
    if flush:
        return (5, *sorted(flush, reverse=True)[:5])
    if straight_high(ranks):
        return (4, straight_high(ranks))
    if trips:
        return (3, trips[0], *sorted((r for r in ranks if r != trips[0]), reverse=True)[:2])
    pairs = sorted((r for r, n in counts.items() if n >= 2), reverse=True)
    if len(pairs) >= 2:
        return (2, *pairs[:2], max(r for r in ranks if r not in pairs[:2]))
    if pairs:
        return (1, pairs[0], *sorted((r for r in ranks if r != pairs[0]), reverse=True)[:3])
    return (0, *sorted(ranks, reverse=True)[:5])


def starting_strength(hole):
    """Documented heuristic for simulation/range priors; not a solver chart."""
    a, b = sorted((RANKS.index(c[0]) + 2 for c in hole), reverse=True)
    value = (a + b - 4) / 24
    if a == b:
        value = 0.55 + a / 32
    else:
        value += 0.07 * (hole[0][1] == hole[1][1]) + 0.05 * (a - b == 1)
    return min(0.99, max(0.05, value))
