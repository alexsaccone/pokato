"""Reproducible synthetic evaluation, separate from runtime coaching."""
from dataclasses import dataclass
import math
import random
from .bayes import SessionModel, ResponseCount, Posterior
from .history import Profile
from .river import RiverTree
from .ranges import parse_range
from pokato.vision.reader import Observation, Seat
from pokato.core.game import Event


@dataclass(frozen=True)
class SyntheticPolicy:
    facing: tuple
    opened: tuple

    def posterior(self, street, owed, pot):
        actions, mean = (("F", "C", "R"), self.facing) if owed else (("K", "R"), self.opened)
        return Posterior(actions, tuple(24*p for p in mean), 0, 0)


def trained_model(policy, opportunities=80, seed=1):
    rng = random.Random(seed)
    counts = []
    for bucket in ("small", "medium", "large", "open"):
        actions, probabilities = (("K", "R"), policy.opened) if bucket == "open" else (("F", "C", "R"), policy.facing)
        draws = rng.choices(actions, probabilities, k=opportunities)
        counts.extend(ResponseCount("R", bucket, action, draws.count(action)) for action in actions)
    return SessionModel(1, tuple(counts))


def paired_report(differences):
    mean = math.fsum(differences) / len(differences)
    se = math.sqrt(math.fsum((x-mean)**2 for x in differences) / (len(differences)-1) / len(differences))
    return {"mean_delta": mean, "paired_95_interval": [mean-1.96*se, mean+1.96*se], "pairs": len(differences)}


def benchmark(pairs=400, seed=31):
    if pairs < 20:
        raise ValueError("At least 20 paired deals required")
    policies = {"folder": SyntheticPolicy((.8, .18, .02), (.8, .2)),
                "station": SyntheticPolicy((.08, .9, .02), (.9, .1)),
                "aggressive": SyntheticPolicy((.15, .35, .5), (.25, .75))}
    reports = {}
    for n, (name, truth) in enumerate(policies.items()):
        learned = trained_model(truth, seed=seed+n)
        baseline = SessionModel(1)
        rng = random.Random(seed+100+n)
        actual = rng.choices(("F", "C", "R"), truth.facing, k=pairs)
        means = [m.posterior("R", 50, 150).mean for m in (baseline, learned)]
        brier = []
        for action in actual:
            scores = [sum((p-int(a == action))**2 for a, p in zip(("F", "C", "R"), mean)) for mean in means]
            brier.append(scores[0]-scores[1])
        # Same hidden cards and same random-number stream for both policies.
        # Small explicit ranges keep the benchmark reproducible and fast.
        seats = (Seat("A", 150, 0, 100), Seat("A", 150, 0, 100),
                 *(Seat("F", 1000, 0, 0) for _ in range(4)))
        o = Observation(1, "R", 0, 0, 200, 0, 10, 150, ("Ks", "Kh"),
                        tuple("Ac 2d 3h 7s 9c".split()), seats, (), 1.)
        fixtures = [("marginal-pair", o, (), {1: parse_range("AsAh, QsQh, 8s6s")}),
                    ("nuts", Observation(2, "R", 0, 0, 200, 0, 10, 150, ("Ah", "Kh"),
                                         tuple("Qh Jh Th 2c 3d".split()), seats, (), 1.),
                     (), {1: parse_range("AsAd, KsKd, 8s6s")}),
                    ("facing-bet", Observation(3, "R", 0, 0, 250, 50, 100, 150, ("Js", "Jd"), o.board,
                         (seats[0], Seat("A", 100, 50, 150), *seats[2:]), (), 1.),
                     (Event(1, 1, "R", "R", 50),), {1: parse_range("AsAh, QsQh, 8s6s")})]
        prepared = []
        choice_report = []
        for fixture_name, observed, events, ranges in fixtures:
            trees = [RiverTree(observed, Profile(1), events, ranges, model=model) for model in (baseline, learned)]
            choices = [max(tree.run().values, key=lambda item: item[1])[0] for tree in trees]
            prepared.append((trees, choices))
            choice_report.append({"fixture": fixture_name, "baseline": choices[0], "adapted": choices[1]})
        profits = []
        for i in range(pairs):
            trees, choices = prepared[i % len(prepared)]
            hidden = rng.randrange(len(trees[0].holes))
            draw_seed = seed*100000+i
            values = [tree.rollout(choice, hidden, random.Random(draw_seed), truth) for tree, choice in zip(trees, choices)]
            profits.append(values[1]-values[0])
        reports[name] = {"training_opportunities_per_context": 80, "fixture_choices": choice_report,
                         "brier_improvement": paired_report(brier),
                         "adapted_minus_baseline_chips": paired_report(profits)}
    return {"seed": seed, "scope": "Synthetic fixed-range river fixtures; not human performance or exploitability", "policies": reports}
