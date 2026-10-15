"""Additive SQLite schema. Original observations are append-only."""
from dataclasses import asdict, dataclass
import json
from pokato.core.cards import validate_cards
from pokato.core.game import Event
from pokato.vision.reader import Observation, Seat
from pokato.analysis.history import Profile


def validate_observation(o):
    validate_cards(o.hole + o.board)
    if len(o.hole) != 2 or len(o.seats) != 6 or len(o.board) not in (0, 3, 4, 5):
        raise ValueError("Invalid cards or seat count")
    if o.street not in ("P", "F", "T", "R", "X") or (o.street != "X" and len(o.board) != {"P": 0, "F": 3, "T": 4, "R": 5}[o.street]):
        raise ValueError("Board and street disagree")
    if type(o.actor) is not int or not -1 <= o.actor < 6 or not 0 <= o.button < 6 or (o.street == "X") != (o.actor == -1):
        raise ValueError("Invalid actor/button")
    numbers = [o.hand, o.pot, o.call, o.minimum, o.maximum]
    numbers += [n for s in o.seats for n in (s.stack, s.bet, s.invested)]
    if any(type(n) is not int or n < 0 for n in numbers):
        raise ValueError("Amounts must be nonnegative integer chips")
    if any(s.status not in ("A", "F", "I") or s.bet > s.invested or
           (s.status == "I" and s.stack != 0) for s in o.seats):
        raise ValueError("Invalid seat status, bet or stack")
    if o.pot != sum(s.invested for s in o.seats):
        raise ValueError("Pot does not match contributions")
    if o.actor >= 0:
        own = o.seats[o.actor]
        price = max(max(s.bet for s in o.seats), 10 if o.street == "P" else 0)
        if own.status != "A" or own.stack <= 0 or o.call != min(own.stack, price - own.bet):
            raise ValueError("Actor or call cost is inconsistent")
        if not 0 <= o.minimum <= o.maximum <= own.stack + own.bet:
            raise ValueError("Invalid raise bounds")
    return o


def observation_dict(o):
    return asdict(o)


def observation_from_dict(data):
    values = dict(data)
    values["seats"] = tuple(Seat(**s) for s in values["seats"])
    values["events"] = tuple(Event(**e) for e in values["events"])
    values["hole"], values["board"] = tuple(values["hole"]), tuple(values["board"])
    return validate_observation(Observation(**values))


@dataclass(frozen=True)
class Snapshot:
    observation: Observation
    events: tuple
    profiles: tuple


@dataclass(frozen=True)
class SavedHand:
    session: str
    hand: int
    created: str
    completed: bool
    count: int


class Archive:
    def __init__(self, connection):
        self.connection = connection
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS replay_hands (
                session TEXT NOT NULL, hand INTEGER NOT NULL,
                created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session, hand))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS replay_snapshots (
                session TEXT NOT NULL, hand INTEGER NOT NULL, seq INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(session, hand, seq))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS replay_scenarios (
                session TEXT NOT NULL, hand INTEGER NOT NULL, seq INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(session, hand, seq))""")

    def save(self, session, observation, events, profiles):
        validate_observation(observation)
        if len(profiles) != 6 or [p.seat for p in profiles] != list(range(6)):
            raise ValueError("Snapshot needs six ordered profile snapshots")
        if [e.seq for e in events] != list(range(1, len(events) + 1)):
            raise ValueError("Cannot archive an incomplete event history")
        payload = json.dumps({"version": 1, "observation": observation_dict(observation),
                              "events": [asdict(e) for e in events], "profiles": [asdict(p) for p in profiles]}, allow_nan=False)
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO replay_hands(session, hand) VALUES (?,?)", (session, observation.hand))
            self.connection.execute("UPDATE replay_hands SET completed=MAX(completed, ?) WHERE session=? AND hand=?",
                                    (int(observation.street == "X"), session, observation.hand))
            self.connection.execute("INSERT OR IGNORE INTO replay_snapshots VALUES (?,?,?,?)",
                                    (session, observation.hand, len(events), payload))

    def hands(self):
        rows = self.connection.execute("""SELECT h.session, h.hand, h.created, h.completed, COUNT(s.seq)
            FROM replay_hands h JOIN replay_snapshots s ON s.session=h.session AND s.hand=h.hand
            GROUP BY h.session, h.hand ORDER BY h.created DESC, h.hand DESC""").fetchall()
        return [SavedHand(session, hand, created, bool(completed), count) for session, hand, created, completed, count in rows]

    def snapshots(self, session, hand):
        rows = self.connection.execute("SELECT payload FROM replay_snapshots WHERE session=? AND hand=? ORDER BY seq",
                                       (session, hand)).fetchall()
        snapshots = []
        for (payload,) in rows:
            data = json.loads(payload)
            if data["version"] != 1:
                raise ValueError("Unsupported replay version")
            snapshots.append(Snapshot(observation_from_dict(data["observation"]),
                                      tuple(Event(**e) for e in data["events"]),
                                      tuple(Profile(**p) for p in data["profiles"])))
        return snapshots

    def scenario(self, session, hand, seq):
        row = self.connection.execute("SELECT payload FROM replay_scenarios WHERE session=? AND hand=? AND seq=?",
                                      (session, hand, seq)).fetchone()
        return json.loads(row[0]) if row else None

    def save_scenario(self, session, hand, seq, observation, ranges):
        validate_observation(observation)
        payload = json.dumps({"version": 1, "observation": observation_dict(observation), "ranges": ranges}, allow_nan=False)
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO replay_scenarios VALUES (?,?,?,?)", (session, hand, seq, payload))

    def reset_scenario(self, session, hand, seq):
        with self.connection:
            self.connection.execute("DELETE FROM replay_scenarios WHERE session=? AND hand=? AND seq=?", (session, hand, seq))
