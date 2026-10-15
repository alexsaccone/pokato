"""Render only public table information plus the hero's hole cards."""
from PIL import Image, ImageDraw
from .layout import WIDTH, HEIGHT, SEATS, paint_field, font

NAMES = ["YOU", "Juniper", "Atlas", "Marlow", "Cedar", "Nova"]


def render(game):
    image = Image.new("RGB", (WIDTH, HEIGHT), "#101c1d")
    d = ImageDraw.Draw(image)
    d.text((24, 12), "POKATO", font=font(25), fill="#e5f3ea")
    d.text((158, 22), "LOCAL PRACTICE  /  NLHE  /  5–10 CHIPS  /  NO RAKE", font=font(12), fill="#98b4a7")
    d.text((24, 91), "Six seats. One decision at a time.", font=font(13), fill="#9aafa8")
    d.rounded_rectangle((195, 155, 784, 559), radius=185, fill="#283f39", outline="#426354", width=3)
    d.rounded_rectangle((211, 171, 768, 543), radius=175, fill="#174b3c", outline="#225c49", width=2)
    d.text((450, 243), "POT", font=font(12), fill="#a5c6b4")
    for text, x in (("HAND", 170), ("STREET", 343), ("TURN", 450), ("BTN", 553)):
        d.text((x, 62), text, font=font(11), fill="#89a99a")
    values = {"marker": "POKATO-V1", "hand": f"{game.hand_id:08d}", "street": game.street,
              "actor": str(game.actor) if game.actor >= 0 else "X", "button": str(game.button),
              "pot": str(game.pot)}
    legal = game.legal()
    values.update(call=str(legal.get("call", 0)), minimum=str(legal.get("min_raise", 0)),
                  maximum=str(legal.get("max_raise", 0)))
    for i, (x, y) in enumerate(SEATS):
        p = game.players[i]
        active = i == game.actor
        d.rounded_rectangle((x, y, x + 174, y + 113), radius=12,
                            fill="#182b29", outline="#d5b576" if active else "#3a554b", width=2)
        d.text((x + 10, y + 8), NAMES[i], font=font(16), fill="#f0d7a1" if active else "#dce8e0")
        for label, dy in (("Stack", 40), ("Bet", 63), ("In pot", 86)):
            d.text((x + 10, y + dy), label, font=font(12), fill="#9aafa8")
        if i == game.button:
            d.ellipse((x - 21, y + 6, x - 2, y + 25), fill="#ead9b2")
            d.text((x - 18, y + 7), "D", font=font(12), fill="#172a25")
        values[f"status{i}"] = "F" if p.folded else ("I" if not p.stack else "A")
        for key, value in (("stack", p.stack), ("bet", p.bet), ("invested", p.invested)):
            values[f"{key}{i}"] = str(value)
    for i in range(5):
        x = 315 + i * 68
        d.rounded_rectangle((x, 302, x + 54, 375), radius=7, fill="#e5e9dc" if i < len(game.board) else "#235342")
        values[f"board{i}"] = game.board[i] if i < len(game.board) else "--"
        if i < len(game.board):
            c = game.board[i]
            d.text((x + 18, 350), {"h": "♥", "d": "♦", "s": "♠", "c": "♣"}[c[1]],
                   font=font(18), fill="#a43535" if c[1] in "hd" else "#142a24")
    for i in range(2):
        x = 450 + i * 44
        d.rounded_rectangle((x, 451, x + 36, 494), radius=5, fill="#e5e9dc")
        values[f"hole{i}"] = game.players[0].hole[i] if game.players[0].hole else "--"
    for i, event in enumerate(game.events[-8:]):
        values[f"event{i}"] = f"{event.seq:04d} {event.seat} {event.street} {event.action} {event.amount:07d}"
    for i in range(len(game.events[-8:]), 8):
        values[f"event{i}"] = " " * 18
    d.line((24, 680, 956, 680), fill="#3a554b")
    d.text((24, 685), "ACTION TAPE · SEQUENCE / SEAT / STREET / ACTION / CHIPS ADDED", font=font(11), fill="#9aafa8")
    d.text((24, 649), "To call", font=font(12), fill="#a6bdb0")
    d.text((235, 649), "Minimum raise-to", font=font(12), fill="#a6bdb0")
    d.text((534, 649), "Maximum raise-to", font=font(12), fill="#a6bdb0")
    d.text((24, 615), (game.result or "P = preflop · F = flop · T = turn · R = river · X = complete")[:110],
           font=font(13), fill="#c1d4c7")
    for key, value in values.items():
        paint_field(image, key, value)
    return image
