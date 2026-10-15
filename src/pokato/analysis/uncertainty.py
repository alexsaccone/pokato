"""Deterministic posterior-policy sensitivity, separate from deal sampling error.

Each draw represents one response policy shared across the entire tree. Small
range quadrature bounds cost; deviations from its mean-policy EV are anchored
to the full-range point estimate. These are approximate sensitivity bands, not
credible intervals for true poker EV or predictions of realized winnings.
"""
from bisect import bisect_right
from dataclasses import dataclass
import math
import random
from .bayes import Posterior, price_bucket
from .ranges import ComboRange
from .turn import TurnTree


class DrawnModel:
    def __init__(self, base, seed):
        self.base, self.seed, self.seat = base, seed, base.seat
        self.cache = {}

    def posterior(self, street, owed, pot):
        key = (street, price_bucket(owed, pot))
        if key not in self.cache:
            original = self.base.posterior(street, owed, pot)
            # String seeds are stable across processes, unlike hash().
            rng = random.Random(f"pokato:{self.seed}:{key[0]}:{key[1]}")
            gamma = tuple(rng.gammavariate(a, 1) if a else 0. for a in original.alpha)
            total = math.fsum(gamma)
            concentration = sum(original.alpha)
            self.cache[key] = Posterior(original.actions, tuple(g/total*concentration for g in gamma),
                                        original.local, original.other, original.prior_strength)
        return self.cache[key]


@dataclass(frozen=True)
class ActionSensitivity:
    label: str
    low: float
    high: float
    best_fraction: float


@dataclass(frozen=True)
class Sensitivity:
    actions: tuple
    draws: int
    hands: int
    total_hands: int
    seed: int
    quadrature_shift: float

    def summary(self, best):
        item = next(a for a in self.actions if a.label == best)
        status = "Stable in draws" if item.best_fraction >= .8 else "Action varies"
        return f"{status} · {item.best_fraction:.0%} of {self.draws} policies"


def compressed_prior(search, limit, seed):
    if limit < 1:
        raise ValueError("Range quadrature needs at least one hand")
    if len(search.holes) <= limit:
        return ComboRange(tuple(zip(search.holes, search.prior_belief)))
    # Systematic stratification approximates the prior weights without
    # using future cards or any opponent's actual hidden hand.
    cumulative, total = [], 0.
    for weight in search.prior_belief:
        total += weight
        cumulative.append(total)
    offset = random.Random(seed).random()
    selected = {}
    for i in range(limit):
        index = min(len(cumulative)-1, bisect_right(cumulative, (i+offset)/limit*total))
        hole = search.holes[index]
        selected[hole] = selected.get(hole, 0.) + 1/limit
    return ComboRange(tuple(selected.items()))


def quantile(values, q):
    ordered = sorted(values)
    position = (len(ordered)-1)*q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high]-ordered[low])*(position-low)


def turn_sensitivity(search, result, profile, events=(), draws=24, hand_limit=32, seed=31):
    if draws < 2:
        raise ValueError("At least two posterior policies required")
    prior = compressed_prior(search, hand_limit, seed)

    def variant(model):
        tree = TurnTree(search.o, profile, events, {search.villain: prior}, model,
                        search.cap, search.river_cap, search.budget)
        # Compression is an internal approximation, not a user override.
        # Automatic ranges must still condition on observed turn actions.
        if not search.explicit_range:
            tree.belief = tree.condition_observed(events)
        return dict(tree.run(details=False).values)

    center = dict(result.values)
    reference = variant(search.model)
    values = {label: [] for label in center}
    best = dict.fromkeys(center, 0.)
    for draw in range(draws):
        sampled = variant(DrawnModel(search.model, f"{seed}:{draw}"))
        anchored = {label: center[label] + sampled[label] - reference[label] for label in center}
        maximum = max(anchored.values())
        winners = [label for label, ev in anchored.items() if math.isclose(ev, maximum, abs_tol=1e-8)]
        for label in winners:
            best[label] += 1/len(winners)
        for label in center:
            values[label].append(anchored[label])
    actions = tuple(ActionSensitivity(label, quantile(values[label], .1), quantile(values[label], .9),
                                      best[label]/draws) for label in center)
    return Sensitivity(actions, draws, len(prior.weights), len(search.holes), seed,
                       max(abs(reference[label]-center[label]) for label in center))
