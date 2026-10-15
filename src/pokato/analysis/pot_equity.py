"""Expected payouts by contribution tier, including refunds and odd chips."""
from dataclasses import dataclass
from itertools import combinations, product
import math
import random
from pokato.core.cards import DECK, evaluate, validate_cards
from pokato.core.pots import build_pots, payout
from .ranges import Distribution, joint_holes
from .equity import Equity, range_weight


@dataclass(frozen=True)
class PotResult:
    amount: int
    eligible: tuple
    refund: bool
    hero_award: float
    error: float

    @property
    def share(self):
        return self.hero_award / self.amount


@dataclass(frozen=True)
class PotEquity:
    equity: Equity
    pots: tuple
    award: float
    error: float


def distributions_for(hero, board, profiles, events=(), ranges=None):
    validate_cards(tuple(hero) + tuple(board))
    if len(hero) != 2 or len(board) not in (0, 3, 4, 5):
        raise ValueError("Need two hero cards and a valid board")
    known = tuple(hero) + tuple(board)
    available = [c for c in DECK if c not in known]
    ranges = ranges or {}
    distributions = []
    for profile in profiles:
        custom = ranges.get(profile.seat)
        values = custom.available(known) if custom is not None else [
            (hole, range_weight(hole, board, events, profile)) for hole in combinations(available, 2)]
        distributions.append(Distribution(values))
    return available, distributions


def calculate_pots(hero, board, profiles, contributions, folded=(), events=(), ranges=None,
                   samples=600, seed=1, button=0):
    if samples < 2:
        raise ValueError("At least two samples required")
    pots = build_pots(contributions, folded)
    if not pots:
        raise ValueError("No pot to analyze")
    seats = [0] + [p.seat for p in profiles]
    if len(set(seats)) != len(seats) or any(i < 0 or i >= len(contributions) for i in seats):
        raise ValueError("Invalid or duplicate opponent seats")
    if any(i not in seats for p in pots if not p.refund for i in p.eligible):
        raise ValueError("An eligible player has no range")
    available, distributions = distributions_for(hero, board, profiles, events, ranges)
    exact = len(board) == 5 and math.prod(len(d.holes) for d in distributions) <= 20000
    rng = random.Random(seed)
    if exact:
        weighted = []
        for d in distributions:
            weights = [d.cumulative[0]] + [b - a for a, b in zip(d.cumulative, d.cumulative[1:])]
            weighted.append(list(zip(d.holes, weights)))
        compatible = []
        for assignment in product(*weighted):
            holes = [hole for hole, weight in assignment]
            cards = [c for hole in holes for c in hole]
            if len(cards) == len(set(cards)):
                compatible.append((holes, math.prod(weight for hole, weight in assignment)))
        exact_total = sum(weight for holes, weight in compatible)
        if not exact_total:
            raise ValueError("Opponent ranges conflict; no compatible deal exists")
        deals = ((holes, list(board), weight / exact_total) for holes, weight in compatible)
        count = len(compatible)
    else:
        def sampled_deals():
            for _ in range(samples):
                holes = joint_holes(rng, distributions)
                used = {c for hole in holes for c in hole}
                runout = list(board) + rng.sample([c for c in available if c not in used], 5 - len(board))
                yield holes, runout, 1 / samples
        deals, count = sampled_deals(), samples
    means, moments = [0.0] * len(pots), [0.0] * len(pots)
    award = award_moment = total_weight = 0.0
    for holes, runout, weight in deals:
        ranks = {0: evaluate(list(hero) + runout)}
        ranks.update({profile.seat: evaluate(list(hole) + runout) for profile, hole in zip(profiles, holes)})
        values = [payout(p, ranks, button, len(contributions)).get(0, 0) for p in pots]
        total = sum(values)
        total_weight += weight
        delta = total - award
        award += weight / total_weight * delta
        award_moment += weight * delta * (total - award)
        for i, value in enumerate(values):
            delta = value - means[i]
            means[i] += weight / total_weight * delta
            moments[i] += weight * delta * (value - means[i])
    def error(moment):
        return 0.0 if exact else math.sqrt(max(0, moment / total_weight) / (count - 1))
    results = tuple(PotResult(p.amount, p.eligible, p.refund, means[i], error(moments[i]))
                    for i, p in enumerate(pots))
    # Equity excludes refunds and pots the hero cannot win. Award uncertainty
    # is computed on complete deals, retaining covariance between side pots.
    contestable = sum(p.amount for p in pots if not p.refund and 0 in p.eligible)
    refunds = sum(r.hero_award for r in results if r.refund)
    se = error(award_moment)
    estimate = Equity((award - refunds) / contestable if contestable else 0,
                      se / contestable if contestable else 0, count, exact)
    return PotEquity(estimate, results, award, se)
