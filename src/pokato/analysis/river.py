"""Bounded heads-up river best response over public beliefs, not hidden hands."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations
import math
from pokato.core.cards import DECK, evaluate
from pokato.core.pots import build_pots, payout
from .bayes import SessionModel, response_probabilities, price_bucket
from .pot_equity import distributions_for


class UnsupportedRiver(ValueError):
    pass


@lru_cache(maxsize=32)
def public_ranks(board):
    deck = [c for c in DECK if c not in board]
    return sorted(evaluate(list(hole) + list(board)) for hole in combinations(deck, 2))


@lru_cache(maxsize=128)
def card_table(hero, board, holes):
    """Shared immutable rank data; blocked hands have zero chance mass."""
    reference = public_ranks(board)
    own = evaluate(list(hero) + list(board))
    outcomes, strengths = [], []
    for hole in holes:
        if set(hole).intersection(board):
            outcomes.append(0)
            strengths.append(0.)
            continue
        rank = evaluate(list(hole) + list(board))
        outcomes.append(0 if own > rank else 1 if own == rank else 2)
        strengths.append((bisect_left(reference, rank) + bisect_right(reference, rank)) / (2*len(reference)))
    return tuple(outcomes), tuple(strengths)


@lru_cache(maxsize=8192)
def terminal_awards(invested, folded, villain, button):
    """Chip tiers do not depend on the particular river card or policy."""
    pots = build_pots(invested, folded)
    return tuple(sum(payout(p, {0: (hero,), villain: (other,)}, button, 6).get(0, 0) for p in pots)
                 for hero, other in ((1, 0), (1, 1), (0, 1)))


@dataclass(frozen=True)
class Move:
    code: str
    target: int = 0
    label: str = ""


@dataclass(frozen=True)
class State:
    stacks: tuple
    bets: tuple
    invested: tuple
    pending: tuple
    actor: int
    last_raise: int = 10
    acted_at: tuple = (-1, -1)
    aggression: int = 0
    folded: int = -1


@dataclass(frozen=True)
class Branch:
    action: str
    response: str
    probability: float
    ev: float
    continuation: str


@dataclass(frozen=True)
class Node:
    ev: float
    choice: object = None
    branches: tuple = ()


@dataclass(frozen=True)
class RiverResult:
    values: tuple
    branches: tuple
    evidence: tuple
    nodes: int
    combinations: int
    aggression_cap: int


class RiverTree:
    street = "R"
    board_length = 5

    def __init__(self, o, profile, events=(), ranges=None, model=None, aggression_cap=3, node_budget=5000):
        if o.street != self.street or o.actor != 0 or len(o.board) != self.board_length:
            raise UnsupportedRiver(f"{self.street} tree requires your matching street decision")
        live = [i for i, s in enumerate(o.seats) if s.status != "F"]
        if len(live) != 2 or 0 not in live:
            raise UnsupportedRiver("River tree requires exactly two live players")
        self.o, self.villain = o, next(i for i in live if i != 0)
        if profile.seat != self.villain:
            raise ValueError("Opponent profile does not match the live player")
        self.model = model or SessionModel(self.villain)
        self.cap, self.budget, self.nodes = aggression_cap, node_budget, 0
        self.memo, self.likelihood_cache, self.outcome_cache = {}, {}, {}
        self.contexts = {}
        self.root = self._initial(events)
        explicit = ranges is not None and ranges.get(self.villain) is not None
        self.explicit_range = explicit
        prior_events = events if explicit else tuple(e for e in events if e.street != self.street)
        _, distributions = distributions_for(o.hole, o.board, [profile], prior_events, ranges)
        dist = distributions[0]
        self.holes = tuple(dist.holes)
        weights = [dist.cumulative[0]] + [b-a for a, b in zip(dist.cumulative, dist.cumulative[1:])]
        self.belief = tuple(w/dist.total for w in weights)
        self.prior_belief = self.belief
        self.outcomes, self.strengths = card_table(tuple(o.hole), tuple(o.board), self.holes)
        if not explicit:
            self.belief = self.condition_observed(events)
        self.folded_seats = {i for i, s in enumerate(o.seats) if s.status == "F"}
        self.baseline_refund = sum(p.amount for p in build_pots(self.root.invested, self.folded_seats)
                                   if p.refund and p.contributors == (0,))

    @classmethod
    def continuation(cls, turn, card):
        """Prepare a river solver whose EV remains relative to the turn root.

        Betting state and card-conditioned beliefs are supplied to solve().
        Root bounds are never reused for a new street.
        """
        child = object.__new__(cls)
        child.o = replace(turn.o, street="R", board=turn.o.board + (card,))
        child.villain, child.model = turn.villain, turn.model
        child.holes, child.root = turn.holes, turn.root
        child.folded_seats, child.baseline_refund = turn.folded_seats, turn.baseline_refund
        child.cap, child.budget, child.nodes = turn.river_cap, turn.budget, 0
        child.memo, child.likelihood_cache, child.outcome_cache, child.contexts = {}, {}, {}, {}
        child.outcomes, child.strengths = card_table(tuple(child.o.hole), tuple(child.o.board), child.holes)
        return child

    def condition_observed(self, events):
        """Condition automatic ranges on actual river decisions using this model.

        Explicit user ranges already describe the current range and bypass
        this step. Preflop/flop/turn inference retains the existing heuristic.
        """
        river = [e for e in events if e.street == self.street]
        pot = self.o.pot - sum(e.amount for e in river)
        bets, acted, last = [0]*6, {}, 10
        active = {i for i, s in enumerate(self.o.seats) if s.status != "F"} | {e.seat for e in river if e.action == "F"}
        belief = self.belief
        for index, e in enumerate(river):
            price = max(bets)
            remaining = {i: self.o.seats[i].stack + sum(f.amount for f in river[index:] if f.seat == i) for i in active}
            if e.seat == self.villain:
                owed = max(0, price-bets[e.seat])
                reopened = e.seat not in acted or price-acted[e.seat] >= last
                can_raise = (reopened and bets[e.seat]+remaining[e.seat] > price and
                             any(remaining[i] > 0 for i in active if i != e.seat))
                posterior = self.model.posterior(self.street, owed, pot)
                likelihood = tuple(response_probabilities(posterior, s, can_raise).get(e.action, 0) for s in self.strengths)
                raw = tuple(w*p for w, p in zip(belief, likelihood))
                total = math.fsum(raw)
                if not total:
                    raise UnsupportedRiver("Observed river action has zero likelihood under the response model")
                belief = tuple(w/total for w in raw)
            bets[e.seat] += e.amount
            if e.action == "R" and bets[e.seat]-price >= last:
                last = bets[e.seat]-price
            if e.action == "F":
                active.discard(e.seat)
            acted[e.seat] = max(bets)
            pot += e.amount
        return belief

    def _initial(self, events):
        seats = (0, self.villain)
        bets, acted, pending, last = [0, 0], [-1, -1], {0, 1}, 10
        river_events = [e for e in events if e.street == self.street]
        for e in river_events:
            if e.seat not in seats:
                continue
            actor = seats.index(e.seat)
            price = max(bets)
            bets[actor] += e.amount
            if e.action == "R":
                increment = bets[actor] - price
                if increment >= last:
                    last = increment
                if bets[1-actor] < bets[actor]:
                    pending.add(1-actor)
            acted[actor] = max(bets)
            pending.discard(actor)
        observed_bets = tuple(self.o.seats[i].bet for i in seats)
        if river_events and tuple(bets) != observed_bets:
            raise UnsupportedRiver("Edited river bets disagree with observed actions; using frozen-contribution scenarios")
        if not river_events:
            bets = list(observed_bets)
            if self.o.call:
                pending = {0}
                acted[1] = max(bets)
                # Manually supplied root bounds can establish a full raise size.
                if self.o.minimum > max(bets) and self.o.minimum < self.o.maximum:
                    last = self.o.minimum - max(bets)
        stacks = tuple(self.o.seats[i].stack for i in seats)
        expected_call = min(stacks[0], max(bets) - bets[0])
        if self.o.call != expected_call:
            raise UnsupportedRiver("Observed call cost disagrees with river bets")
        if self.o.minimum == self.o.maximum == 0 and stacks[1] > 0 and stacks[0] + bets[0] > max(bets):
            raise UnsupportedRiver("Corrected or unavailable root raise bounds; using frozen-contribution scenarios")
        pending = {i for i in pending if stacks[i] > 0}
        if 0 not in pending:
            raise UnsupportedRiver("Observed river action order does not match the pending decision")
        return State(stacks, tuple(bets), tuple(s.invested for s in self.o.seats), tuple(sorted(pending)), 0, last, tuple(acted))

    def moves(self, state, root=False):
        actor, other = state.actor, 1-state.actor
        price = max(state.bets)
        owed = min(state.stacks[actor], price - state.bets[actor])
        moves = [Move("F", label="Fold"), Move("C", label="Call")] if owed else [Move("K", label="Check")]
        ceiling = state.bets[actor] + state.stacks[actor]
        reopened = state.acted_at[actor] < 0 or price - state.acted_at[actor] >= state.last_raise
        minimum = min(ceiling, price + state.last_raise)
        if root:
            minimum = self.o.minimum
            ceiling = min(ceiling, self.o.maximum) if self.o.maximum else ceiling
        if not minimum or not reopened or state.aggression >= self.cap or ceiling <= price or not state.stacks[other]:
            return tuple(moves)
        pot_after_call = sum(state.invested) + owed
        targets = sorted({min(ceiling, max(minimum, price + max(10, round(pot_after_call*f))))
                          for f in (1/3, 2/3)} | {ceiling})
        for target in targets:
            moves.append(Move("R", target, f"Raise to {target}" if price else f"Bet {target}"))
        return tuple(moves)

    def step(self, state, move):
        actor, other = state.actor, 1-state.actor
        if move.code == "F":
            return replace(state, pending=(), folded=actor)
        price = max(state.bets)
        stacks, bets, invested, acted = list(state.stacks), list(state.bets), list(state.invested), list(state.acted_at)
        pending = set(state.pending)
        pending.discard(actor)
        amount = move.target - bets[actor] if move.code == "R" else min(stacks[actor], price - bets[actor]) if move.code == "C" else 0
        stacks[actor] -= amount
        bets[actor] += amount
        invested[0 if actor == 0 else self.villain] += amount
        last = state.last_raise
        if move.code == "R":
            increment = move.target - price
            if increment >= last:
                last = increment
            if stacks[other] and bets[other] < move.target:
                pending.add(other)
        acted[actor] = max(bets)
        pending = {i for i in pending if stacks[i] > 0}
        if sum(stack > 0 for stack in stacks) <= 1:
            pending = {i for i in pending if bets[i] < max(bets)}
        return State(tuple(stacks), tuple(bets), tuple(invested), tuple(sorted(pending)), other,
                     last, tuple(acted), state.aggression + int(move.code == "R"))

    def terminal(self, state, belief):
        folded = self.folded_seats | ({0 if state.folded == 0 else self.villain} if state.folded >= 0 else set())
        awards = terminal_awards(state.invested, tuple(sorted(folded)), self.villain, self.o.button)
        masses = self.outcome_cache.get(belief)
        if masses is None:
            masses = tuple(math.fsum(w for w, outcome in zip(belief, self.outcomes) if outcome == i) for i in range(3))
            self.outcome_cache[belief] = masses
        spent = self.root.stacks[0] - state.stacks[0]
        return math.fsum(p*a for p, a in zip(masses, awards)) - spent - self.baseline_refund

    def likelihoods(self, state, moves, model=None):
        model = model or self.model
        # Use the nominal price, matching context extraction from observed
        # event prefixes; legal short calls are clipped separately by step().
        owed = max(state.bets)-state.bets[1]
        posterior = model.posterior(self.street, owed, sum(state.invested))
        raises = [m for m in moves if m.code == "R"]
        key = (posterior.alpha, bool(raises), tuple(moves))
        if model is self.model:
            self.contexts[price_bucket(owed, sum(state.invested))] = posterior
            if key in self.likelihood_cache:
                return self.likelihood_cache[key]
        rows = []
        for move in moves:
            rows.append(tuple(response_probabilities(posterior, s, bool(raises)).get(move.code, 0) /
                              (len(raises) if move.code == "R" else 1) for s in self.strengths))
        if model is self.model:
            self.likelihood_cache[key] = tuple(rows)
        return tuple(rows)

    def solve(self, state, belief):
        if not state.pending:
            return Node(self.terminal(state, belief))
        key = (state, belief)
        if key in self.memo:
            return self.memo[key]
        self.nodes += 1
        if self.nodes > self.budget:
            raise UnsupportedRiver("River tree exceeded its bounded search budget")
        moves = self.moves(state)
        if state.actor == 0:
            results = [(self.solve(self.step(state, move), belief), move) for move in moves]
            value, choice = max(results, key=lambda item: item[0].ev)
            result = Node(value.ev, choice)
        else:
            branches = []
            for move, likelihood in zip(moves, self.likelihoods(state, moves)):
                raw = tuple(w*p for w, p in zip(belief, likelihood))
                probability = math.fsum(raw)
                if probability <= 0:
                    continue
                updated = tuple(w/probability for w in raw)
                child = self.solve(self.step(state, move), updated)
                branches.append((move, probability, child))
            result = Node(math.fsum(p*child.ev for move, p, child in branches), branches=tuple(branches))
        self.memo[key] = result
        return result

    def run(self, details=True):
        values, branches = [], []
        for move in self.moves(self.root, root=True):
            node = self.solve(self.step(self.root, move), self.belief)
            values.append((move.label, node.ev))
            branches.extend(Branch(move.label, response.label, p, child.ev,
                                   child.choice.label if child.choice else "terminal payout")
                            for response, p, child in node.branches if details)
        evidence = []
        for context, posterior in sorted(self.contexts.items()) if details else ():
            intervals = []
            for action, mean in zip(posterior.actions, posterior.mean):
                low, high = posterior.interval(action)
                intervals.append(f"{action} {mean:.0%} [{low:.0%}, {high:.0%}]")
            evidence.append(f"River/{context}: {posterior.local} direct, {posterior.other} borrowed opportunities; "
                            f"data weight {posterior.data_weight:.0%}; " + ", ".join(intervals))
        return RiverResult(tuple(values), tuple(branches), tuple(evidence), self.nodes, len(self.holes), self.cap)

    def rollout(self, root_label, hidden_index, rng, actual_model):
        """Synthetic benchmark only: evaluate a public-belief policy on a dealt hand."""
        move = next(m for m in self.moves(self.root, root=True) if m.label == root_label)
        state, belief = self.step(self.root, move), self.belief
        while state.pending:
            if state.actor == 0:
                move = self.solve(state, belief).choice
            else:
                moves = self.moves(state)
                true_rows = self.likelihoods(state, moves, actual_model)
                probabilities = [row[hidden_index] for row in true_rows]
                move = rng.choices(moves, probabilities)[0]
                assumed = self.likelihoods(state, moves)[moves.index(move)]
                raw = tuple(w*p for w, p in zip(belief, assumed))
                total = math.fsum(raw)
                belief = tuple(w/total for w in raw)
            state = self.step(state, move)
        dealt = tuple(float(i == hidden_index) for i in range(len(self.holes)))
        return self.terminal(state, dealt)
