"""Local SQLite observations, idempotent across repeated screen captures."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class Profile:
    seat: int
    hands: int = 0
    vpip_count: int = 0
    pfr_count: int = 0
    faced: int = 0
    folds: int = 0

    @property
    def vpip(self):
        return (self.vpip_count + 2) / (self.hands + 5)

    @property
    def fold_rate(self):
        return (self.folds + 3) / (self.faced + 6)


class History:
    def __init__(self, path=":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS events (
            session TEXT NOT NULL, hand INTEGER NOT NULL, seq INTEGER NOT NULL,
            seat INTEGER NOT NULL, street TEXT NOT NULL, action TEXT NOT NULL,
            amount INTEGER NOT NULL, faced INTEGER NOT NULL,
            PRIMARY KEY(session, hand, seq))""")

    def record(self, session, hand, events):
        """Record a complete observed prefix. Seat IDs refer to fixed practice identities."""
        bets, street = [0] * 6, "P"
        with self.connection:
            for e in events:
                if e.street != street:
                    bets, street = [0] * 6, e.street
                price = max(max(bets), 10 if street == "P" else 0)
                faced = int(e.action != "B" and price > bets[e.seat])
                self.connection.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?)",
                                        (session, hand, e.seq, e.seat, e.street, e.action, e.amount, faced))
                bets[e.seat] += e.amount

    def profile(self, seat):
        rows = self.connection.execute("""SELECT session, hand,
            MAX(CASE WHEN street='P' AND action!='B' THEN 1 ELSE 0 END),
            MAX(CASE WHEN street='P' AND action IN ('C','R') THEN 1 ELSE 0 END),
            MAX(CASE WHEN street='P' AND action='R' THEN 1 ELSE 0 END),
            SUM(faced), SUM(CASE WHEN faced=1 AND action='F' THEN 1 ELSE 0 END)
            FROM events WHERE seat=? GROUP BY session, hand""", (seat,)).fetchall()
        return Profile(seat, *(sum(row[i] for row in rows) for i in range(2, 7)))

    def close(self):
        self.connection.close()
