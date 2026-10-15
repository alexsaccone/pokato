"""Intentionally simple, varied practice opponents; no access to hero's cards."""
from pokato.core.cards import starting_strength, evaluate

PROFILES = [(0.5, 0.2), (0.75, 0.12), (0.4, 0.45), (0.55, 0.3), (0.35, 0.55), (0.6, 0.1)]


def choose_action(game):
    seat = game.actor
    p = game.players[seat]
    tightness, aggression = PROFILES[seat]
    strength = starting_strength(p.hole)
    if len(game.board) >= 3:
        rank = evaluate(p.hole + game.board)
        strength = min(0.98, 0.2 + rank[0] * 0.14 + rank[1] / 100)
    legal = game.legal()
    roll = game.rng.random()
    if legal["call"] and strength + game.rng.uniform(-0.25, 0.25) < tightness - 0.1:
        return "F", 0
    if legal["min_raise"] and roll < aggression * strength:
        target = max(legal["min_raise"], p.bet + legal["call"] + max(10, game.pot // 2))
        return "R", min(legal["max_raise"], target)
    return ("K" if legal["check"] else "C"), 0
