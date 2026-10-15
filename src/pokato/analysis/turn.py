"""Heads-up turn search with exact card removal and public-belief river play."""
from dataclasses import dataclass, replace
import math
from pokato.core.cards import DECK
from pokato.core.pots import build_pots, payout
from .equity import Equity
from .pot_equity import PotEquity, PotResult
from .river import RiverTree, State, UnsupportedRiver


@dataclass(frozen=True)
class Runout:
    card: str
    probability: float
    share: float
    tie: float = 0.


@dataclass(frozen=True)
class TurnResult:
    values: tuple
    branches: tuple
    evidence: tuple
    nodes: int
    combinations: int
    aggression_cap: int
    runouts: tuple
    river_cap: int


class TurnTree(RiverTree):
    street = "T"
    board_length = 4

    def __init__(self, o, profile, events=(), ranges=None, model=None,
                 aggression_cap=1, river_cap=1, node_budget=20000):
        self.river_cap = river_cap
        self.rivers = {}
        self.chance_cache = {}
        self.chance_nodes = 0
        super().__init__(o, profile, events, ranges, model, aggression_cap, node_budget)
        self.cards = tuple(c for c in DECK if c not in o.hole + o.board)

    def chance(self, belief):
        """P(card) = compatible hand mass / 44, then condition on that card.

        There are 46 unseen cards from hero's view, but only 44 available
        for each particular opponent hand. Marginals need not be uniform.
        """
        for card in self.cards:
            raw = tuple(w if card not in hole else 0. for w, hole in zip(belief, self.holes))
            mass = math.fsum(raw)
            if mass > 0:
                yield card, mass / 44, tuple(w / mass for w in raw)

    def river_state(self, state):
        seats = (0, self.villain)
        first = min(range(2), key=lambda i: (seats[i] - self.o.button - 1) % 6)
        # A lone player with chips cannot bet into an all-in opponent.
        pending = (0, 1) if all(s > 0 for s in state.stacks) else ()
        return State(state.stacks, (0, 0), state.invested, pending, first)

    def terminal(self, state, belief):
        if state.folded >= 0:
            return super().terminal(state, belief)
        key = (state, belief)
        if key in self.chance_cache:
            return self.chance_cache[key]
        river_state = self.river_state(state)
        values = []
        for card, probability, updated in self.chance(belief):
            if card not in self.rivers:
                self.rivers[card] = RiverTree.continuation(self, card)
            river = self.rivers[card]
            before = river.nodes
            node = river.solve(river_state, updated)
            self.chance_nodes += river.nodes - before
            if self.nodes + self.chance_nodes > self.budget:
                raise UnsupportedRiver("Turn/river tree exceeded its bounded search budget")
            values.append(probability * node.ev)
        result = math.fsum(values)
        self.chance_cache[key] = result
        return result

    def run(self, details=True):
        base = super().run(details)
        if not details:
            return TurnResult(base.values, (), (), self.nodes + self.chance_nodes,
                              base.combinations, self.cap, (), self.river_cap)
        evidence = [line.replace("River/", "Turn/") for line in base.evidence]
        # A context's evidence is independent of the river card. Avoid
        # repeating identical response intervals for all 46 possible cards.
        river_contexts = {}
        for river in self.rivers.values():
            river_contexts.update(river.contexts)
        for context, posterior in sorted(river_contexts.items()):
            intervals = []
            for action, mean in zip(posterior.actions, posterior.mean):
                low, high = posterior.interval(action)
                intervals.append(f"{action} {mean:.0%} [{low:.0%}, {high:.0%}]")
            evidence.append(f"River/{context}: {posterior.local} direct, {posterior.other} borrowed opportunities; "
                            f"data weight {posterior.data_weight:.0%}; " + ", ".join(intervals))
        runouts = []
        for card, probability, belief in self.chance(self.belief):
            if card not in self.rivers:
                self.rivers[card] = RiverTree.continuation(self, card)
            outcomes = self.rivers[card].outcomes
            share = math.fsum(w * (1. if outcome == 0 else .5 if outcome == 1 else 0.)
                              for w, outcome in zip(belief, outcomes))
            tie = math.fsum(w for w, outcome in zip(belief, outcomes) if outcome == 1)
            runouts.append(Runout(card, probability, share, tie))
        branches = tuple(replace(b, continuation="river card → public-belief river play"
                                 if b.continuation == "terminal payout" and b.response != "Fold"
                                 else b.continuation) for b in base.branches)
        return TurnResult(base.values, branches, tuple(evidence), self.nodes + self.chance_nodes,
                          base.combinations, self.cap, tuple(runouts), self.river_cap)

    def showdown_pots(self, result, contributions):
        """Exact check/call-then-showdown equity, distinct from strategy EV."""
        tie = math.fsum(r.probability*r.tie for r in result.runouts)
        win = math.fsum(r.probability*(r.share-.5*r.tie) for r in result.runouts)
        probabilities = (win, tie, max(0., 1-win-tie))
        results = []
        for pot in build_pots(contributions, self.folded_seats):
            awards = [payout(pot, {0: (hero,), self.villain: (other,)}, self.o.button, 6).get(0, 0)
                      for hero, other in ((1, 0), (1, 1), (0, 1))]
            award = math.fsum(p*a for p, a in zip(probabilities, awards))
            results.append(PotResult(pot.amount, pot.eligible, pot.refund, award, 0.))
        award = math.fsum(p.hero_award for p in results)
        refunds = math.fsum(p.hero_award for p in results if p.refund)
        contestable = sum(p.amount for p in results if not p.refund and 0 in p.eligible)
        equity = Equity((award-refunds)/contestable if contestable else 0., 0., len(self.holes)*44, True)
        return PotEquity(equity, tuple(results), award, 0.)
