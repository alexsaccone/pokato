"""Slow test-only oracle: 5-card enumeration and one-chip-at-a-time payouts.

Does not import the production evaluator, pot builder, or settlement functions.
"""
from collections import Counter
from itertools import combinations


def rank_five(cards):
    values = sorted(("23456789TJQKA".index(card[0]) + 2 for card in cards), reverse=True)
    groups = Counter(values)
    order = sorted(groups, key=lambda n: (groups[n], n), reverse=True)
    pattern = sorted(groups.values(), reverse=True)
    straight = 5 if values == [14, 5, 4, 3, 2] else values[0] if len(groups) == 5 and values[0] - values[-1] == 4 else 0
    flush = len({card[1] for card in cards}) == 1
    if flush and straight:
        return (8, straight)
    if pattern == [4, 1]:
        return (7, *order)
    if pattern == [3, 2]:
        return (6, *order)
    if flush:
        return (5, *values)
    if straight:
        return (4, straight)
    if pattern == [3, 1, 1]:
        return (3, *order)
    if pattern == [2, 2, 1]:
        return (2, *order)
    if pattern == [2, 1, 1, 1]:
        return (1, *order)
    return (0, *values)


def rank_seven(cards):
    return max(rank_five(five) for five in combinations(cards, 5))


def chip_payouts(contributions, folded, ranks, button):
    # Build layers one chip at a time, then coalesce identical participants
    # before distributing odd chips. This independently defines pot sizes.
    layers = {}
    for chip in range(1, max(contributions) + 1):
        participants = tuple(i for i, amount in enumerate(contributions) if amount >= chip)
        layers[participants] = layers.get(participants, 0) + len(participants)
    awards = [0] * len(contributions)
    for participants, amount in layers.items():
        if len(participants) == 1:
            awards[participants[0]] += amount
            continue
        eligible = [i for i in participants if i not in folded]
        winners = [i for i in eligible if ranks[i] == max(ranks[j] for j in eligible)]
        winners.sort(key=lambda i: (i - button - 1) % len(contributions))
        for chip in range(amount):
            awards[winners[chip % len(winners)]] += 1
    return awards
