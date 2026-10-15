"""Session-only weighted Dirichlet response adaptation with conservative priors."""
from dataclasses import dataclass
from functools import lru_cache
import random


def price_bucket(owed, pot):
    if owed <= 0:
        return "open"
    ratio = owed / max(1, pot)
    return "small" if ratio <= .25 else "medium" if ratio <= .5 else "large"


@dataclass(frozen=True)
class ResponseCount:
    street: str
    bucket: str
    action: str
    count: int


@dataclass(frozen=True)
class Posterior:
    actions: tuple
    alpha: tuple
    local: int
    other: int
    prior_strength: float = 24.0

    @property
    def mean(self):
        return tuple(a / sum(self.alpha) for a in self.alpha)

    @property
    def data_weight(self):
        return 1 - self.prior_strength / sum(self.alpha)

    def interval(self, action):
        index = self.actions.index(action)
        if self.alpha[index] == 0:
            return (0.0, 0.0)
        if sum(self.alpha) == self.alpha[index]:
            return (1.0, 1.0)
        return marginal_interval(self.alpha[index], sum(self.alpha) - self.alpha[index])


@lru_cache(maxsize=1024)
def marginal_interval(a, b):
    """Deterministic sampled 90% marginal posterior interval, not an EV CI."""
    rng = random.Random(19)
    draws = sorted(rng.betavariate(a, b) for _ in range(2000))
    return draws[100], draws[1899]


@dataclass(frozen=True)
class SessionModel:
    seat: int
    counts: tuple = ()

    @property
    def opportunities(self):
        return sum(c.count for c in self.counts)

    @lru_cache(maxsize=4096)
    def posterior(self, street, owed, pot):
        bucket = price_bucket(owed, pot)
        actions = ("K", "R") if bucket == "open" else ("F", "C", "R")
        # Deliberately conservative, explicit design priors, not measured
        # population frequencies: 24 pseudo-observations in each context.
        alpha = [18.0, 6.0] if bucket == "open" else [10.0, 11.0, 3.0]
        local = other = 0
        for c in self.counts:
            if (c.bucket == "open") != (bucket == "open") or c.action not in actions:
                continue
            same = c.street == street and c.bucket == bucket
            weight = 1.0 if same else .25 if c.street == street else .1
            alpha[actions.index(c.action)] += weight * c.count
            if same:
                local += c.count
            else:
                other += c.count
        return Posterior(actions, tuple(alpha), local, other)


def model_from_dict(data):
    counts = tuple(ResponseCount(**c) for c in data["counts"])
    if not 0 <= data["seat"] < 6 or any(
            c.street not in ("P", "F", "T", "R") or c.bucket not in ("open", "small", "medium", "large") or
            c.action not in (("K", "R") if c.bucket == "open" else ("F", "C", "R"))
            for c in counts):
        raise ValueError("Invalid session model")
    if any(type(c.count) is not int or c.count < 0 for c in counts):
        raise ValueError("Invalid session evidence count")
    return SessionModel(data["seat"], counts)


def response_probabilities(posterior, strength, can_raise=True):
    """Bayesian marginal response rates plus a transparent hand-strength tilt.

    The percentile uses only the opponent's own hypothetical hand and public
    board. It never compares to the hero's actual hand to choose an action.
    """
    s = max(0.0, min(1.0, strength))
    tilt = {"F": 1.7 - 1.5*s, "C": .7 + .6*s,
            "R": .15 + 1.8*s**3 + .25*(1-s)**3, "K": 1.5 - .7*s}
    weights = {a: p * tilt[a] for a, p in zip(posterior.actions, posterior.mean) if a != "R" or can_raise}
    total = sum(weights.values())
    return {a: weight / total for a, weight in weights.items()}
