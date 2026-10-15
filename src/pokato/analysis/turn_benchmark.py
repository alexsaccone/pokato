"""Fixed-fixture arithmetic, latency and sensitivity-resolution diagnostics."""
from dataclasses import asdict, replace
import time
from pokato.vision.reader import Observation, Seat
from pokato.core.game import Event
from .history import Profile
from .ranges import parse_range
from .turn import TurnTree
from .uncertainty import turn_sensitivity


def fixtures():
    seats = (Seat("A", 300, 0, 100), Seat("A", 300, 0, 100),
             *(Seat("F", 1000, 0, 0) for _ in range(4)))
    wide = Observation(1, "T", 0, 0, 200, 0, 10, 300, ("Ks", "Kh"),
                       tuple("Ac 2d 3h 7s".split()), seats, (), 1.)
    draw = replace(wide, hole=("As", "Qs"), board=tuple("Ks Ts 2d 7c".split()),
                   seats=(Seat("A", 120, 0, 100), Seat("A", 90, 30, 130), *seats[2:]),
                   pot=230, call=30, minimum=60, maximum=120, button=1)
    short = replace(wide, seats=(Seat("A", 30, 0, 100), Seat("I", 0, 50, 150), *seats[2:]),
                    pot=250, call=30, minimum=0, maximum=0)
    return {
        "wide": (wide, (), None),
        "draw": (draw, (Event(1, 1, "T", "R", 30),), {1: parse_range("JhJd, AcAd, 9c9d, 8h8d")}),
        "short-allin": (short, (Event(1, 1, "T", "R", 50),), {1: parse_range("QsQh")}),
    }


def benchmark_case(name, draws=24, hands=32, reference_hands=64, seed=31):
    o, events, ranges = fixtures()[name]
    profile = Profile(1)
    start = time.perf_counter()
    tree = TurnTree(o, profile, events, ranges)
    point = tree.run()
    point_seconds = time.perf_counter()-start
    sensitivity = turn_sensitivity(tree, point, profile, events, draws, hands, seed)
    sensitivity_seconds = time.perf_counter()-start-point_seconds
    contributions = [s.invested for s in o.seats]
    contributions[0] += o.call
    equity = tree.showdown_pots(point, contributions).equity
    report = {
        "case": name,
        "point_seconds": round(point_seconds, 3),
        "sensitivity_seconds": round(sensitivity_seconds, 3),
        "nodes": point.nodes,
        "combinations": point.combinations,
        "river_cards": len(point.runouts),
        "card_probability_mass": sum(r.probability for r in point.runouts),
        "showdown_equity": equity.share,
        "enumerated_deals": equity.samples,
        "actions": dict(point.values),
        "best": max(point.values, key=lambda item: item[1])[0],
        "sensitivity": asdict(sensitivity),
    }
    if reference_hands > hands and len(tree.holes) > hands:
        finer = turn_sensitivity(tree, point, profile, events, draws, reference_hands, seed)
        report["resolution_check"] = {
            "reference_hands": finer.hands,
            "reference_quadrature_shift": finer.quadrature_shift,
            "max_band_endpoint_change": max(max(abs(a.low-b.low), abs(a.high-b.high))
                                            for a, b in zip(sensitivity.actions, finer.actions)),
            "max_policy_agreement_change": max(abs(a.best_fraction-b.best_fraction)
                                               for a, b in zip(sensitivity.actions, finer.actions)),
        }
    return report
