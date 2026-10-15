"""Contribution tiers and integer-chip payouts, independent of game state."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Pot:
    amount: int
    contributors: tuple
    eligible: tuple
    refund: bool = False


def build_pots(contributions, folded=()):
    if not contributions or any(type(n) is not int or n < 0 for n in contributions):
        raise ValueError("Contributions must be nonnegative integer chips")
    folded = set(folded)
    previous, pots = 0, []
    for level in sorted(set(contributions) - {0}):
        contributors = tuple(i for i, amount in enumerate(contributions) if amount >= level)
        refund = len(contributors) == 1
        eligible = contributors if refund else tuple(i for i in contributors if i not in folded)
        if not eligible:
            raise ValueError("Contribution tier has no eligible player")
        pots.append(Pot((level - previous) * len(contributors), contributors, eligible, refund))
        previous = level
    return tuple(pots)


def payout(pot, ranks, button, seat_count):
    if pot.refund:
        return {pot.contributors[0]: pot.amount}
    best = max(ranks[i] for i in pot.eligible)
    winners = sorted((i for i in pot.eligible if ranks[i] == best),
                     key=lambda i: (i - button - 1) % seat_count)
    return {seat: pot.amount // len(winners) + int(n < pot.amount % len(winners))
            for n, seat in enumerate(winners)}
