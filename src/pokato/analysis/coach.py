from dataclasses import dataclass
import random
from pokato.core.cards import starting_strength, evaluate, CATEGORIES
from .equity import showdown_share
from .pot_equity import calculate_pots, distributions_for
from .ranges import joint_holes
from pokato.core.pots import build_pots
from .bayes import SessionModel
from .river import RiverTree, UnsupportedRiver
from .ranges import ComboRange


@dataclass(frozen=True)
class ActionValue:
    label: str
    ev: float
    error: float = 0


@dataclass(frozen=True)
class Advice:
    equity: object
    threshold: float
    actions: tuple
    recommendation: str
    assumptions: str
    hand_name: str
    pots: tuple = ()
    pot_odds_valid: bool = True
    engine: str = "scenario"
    branches: tuple = ()
    evidence: tuple = ()
    nodes: int = 0


def raise_value(o, profiles, events, target, samples, seed, ranges=None):
    """One-step fold/call scenario with strength-conditioned opponent responses.

    No reraises or future bets. Everyone pays the same target; caller hands
    remain conditioned on observed actions and response strength. Folded
    cards stay removed from the runout. Unsupported all-in/side-pot cases
    are excluded by analyze().
    """
    rng = random.Random(seed)
    own = o.seats[0]
    cost = target - own.bet
    results = []
    available, distributions = distributions_for(o.hole, o.board, profiles, events, ranges)
    for _ in range(samples):
        holes = joint_holes(rng, distributions)
        used = {c for hole in holes for c in hole}
        deck = [c for c in available if c not in used]
        callers = []
        extra = 0
        for profile, hole in zip(profiles, holes):
            hole = list(hole)
            strength = starting_strength(hole)
            if len(o.board) >= 3:
                rank = evaluate(hole + list(o.board))
                strength = min(0.98, 0.25 + rank[0] * 0.13 + rank[1] / 100)
            payment = target - o.seats[profile.seat].bet
            pressure = payment / max(1, o.pot + cost)
            fold_chance = min(0.95, max(0.05, profile.fold_rate + 0.4 * pressure - 0.55 * (strength - 0.5)))
            if rng.random() >= fold_chance:
                callers.append(hole)
                extra += payment
        if not callers:
            results.append(float(o.pot))
        else:
            runout = list(o.board) + rng.sample(deck, 5 - len(o.board))
            share = showdown_share(o.hole, runout, callers)
            results.append(share * (o.pot + cost + extra) - cost)
    mean = sum(results) / samples
    se = (sum((x - mean) ** 2 for x in results) / (samples - 1) / samples) ** 0.5
    return ActionValue(f"Raise to {target}", mean, se)


def analyze(o, profiles, events=(), samples=600, ranges=None, models=()):
    if o.actor != 0 or o.street == "X" or o.seats[0].status != "A":
        return None
    opponents = [profiles[i] for i, s in enumerate(o.seats) if i != 0 and s.status != "F"]
    contributions = [s.invested for s in o.seats]
    current_pots = build_pots(contributions, [i for i, s in enumerate(o.seats) if s.status == "F"])
    baseline_refund = sum(p.amount for p in current_pots if p.refund and p.contributors == (0,))
    contributions[0] += o.call
    result = calculate_pots(o.hole, o.board, opponents, contributions,
                            [i for i, s in enumerate(o.seats) if s.status == "F"], events, ranges,
                            samples, seed=o.hand * 101 + len(events), button=o.button)
    estimate = result.equity
    contested = [p for p in result.pots if not p.refund and 0 in p.eligible]
    odds_valid = len(contested) == 1 and len(contested[0].eligible) > 1
    threshold = o.call / contested[0].amount if o.call and odds_valid else 0
    name = CATEGORIES[evaluate(list(o.hole + o.board))[0]] if len(o.board) >= 3 else "Preflop"
    all_in = any(s.status == "I" for s in o.seats)
    own = o.seats[0]
    max_bet = max(s.bet for s in o.seats)
    action = "Call" if o.call else "Check"
    terminal = o.street == "R" and len(opponents) == 1 and all(
        s.status == "F" or s.bet == max_bet for i, s in enumerate(o.seats) if i != 0)
    base = ActionValue(action, result.award - o.call - baseline_refund, result.error)
    fallback = ""
    if o.street == "R" and len(opponents) == 1:
        try:
            villain = opponents[0].seat
            model = next((m for m in models if m.seat == villain), SessionModel(villain))
            search = RiverTree(o, opponents[0], events, ranges, model)
            tree = search.run()
            current_ranges = dict(ranges or {})
            current_ranges[villain] = ComboRange(tuple(zip(search.holes, search.belief)))
            result = calculate_pots(o.hole, o.board, opponents, contributions,
                                    [i for i, s in enumerate(o.seats) if s.status == "F"], events, current_ranges,
                                    samples, seed=o.hand*101+len(events), button=o.button)
            estimate = result.equity
            values = tuple(sorted((ActionValue(label, ev) for label, ev in tree.values), key=lambda a: a.ev, reverse=True))
            assumption = (f"Heads-up river tree: {tree.nodes} decision nodes, {tree.combinations} weighted combinations; "
                          f"at most {tree.aggression_cap} additional bets/raises, then fold/call only. "
                          "Sizing menu: one-third pot, two-thirds pot and all-in, bounded by legal limits. "
                          "Hero continuations maximize expected EV over updated beliefs, never revealed opponent cards. "
                          "Response priors use current-session observations with a heuristic public-board strength tilt; "
                          "raise sizings have uniform conditional weight. Exact integration within this restricted model "
                          "does not include response/range uncertainty. No rake or GTO guarantee.")
            evidence = tree.evidence or ("No future opponent response: terminal fold/call/check.",)
            if not models:
                evidence = ("No saved session model: baseline response priors.",) + evidence
            return Advice(estimate, threshold, values, f"{values[0].label} · best modeled tree EV", assumption,
                          name, result.pots, odds_valid, "river-tree", tree.branches, evidence, tree.nodes)
        except UnsupportedRiver as exc:
            fallback = str(exc) + ". "
    actions = ([ActionValue("Fold", 0)] if o.call else []) + [base]
    target = max(o.minimum, own.bet + o.call + max(10, o.pot // 2))
    if not all_in and o.minimum and target <= o.maximum and all(
            s.status == "F" or i == 0 or s.stack + s.bet >= target for i, s in enumerate(o.seats)):
        actions.append(raise_value(o, opponents, events, target, samples, o.hand * 301 + len(events), ranges))
    actions.sort(key=lambda a: a.ev, reverse=True)
    best = actions[0]
    close = len(actions) > 1 and best.ev - actions[1].ev <= 1.96 * (best.error ** 2 + actions[1].error ** 2) ** 0.5
    recommendation = f"{best.label} · best modeled EV" + (" · sampling tie" if close else "")
    assumption = ("Call/fold: terminal HU river calculation against the selected range. " if terminal and o.call
                  else "Check/call scenario: freeze contributions after your action, then showdown; remaining decisions are omitted. ")
    assumption += "Pots include eligibility, integer splits and uncalled refunds. Equity is weighted over pots you can win. "
    assumption += ("Raises omitted in all-in states. " if all_in else "Raises: heuristic fold/call, no reraises or future bets. ")
    assumption = fallback + assumption + "No rake. Sampling intervals exclude range/model uncertainty."
    return Advice(estimate, threshold, tuple(actions), recommendation, assumption, name, result.pots, odds_valid)
