"""Render a public observation without a Game, deck, or hidden hole cards."""
from types import SimpleNamespace
from pokato.simulator.render import render, NAMES


def render_observation(o):
    players = [SimpleNamespace(name=NAMES[i], stack=s.stack, bet=s.bet, invested=s.invested,
                               folded=s.status == "F", hole=o.hole if i == 0 else ()) for i, s in enumerate(o.seats)]
    table = SimpleNamespace(players=players, hand_id=o.hand, street=o.street, actor=o.actor,
                            button=o.button, pot=o.pot, board=o.board, events=o.events,
                            result="Saved observation · select an earlier decision to analyze" if o.street == "X" else "Saved observation · original information only",
                            legal=lambda: {"call": o.call, "min_raise": o.minimum, "max_raise": o.maximum})
    return render(table)
