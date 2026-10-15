from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from pokato.analysis.history import History, Profile
from pokato.core.game import Game
from pokato.simulator.render import render
from pokato.vision.reader import Reader
from pokato.replay.store import Archive


class ReplayStoreTests(unittest.TestCase):
    def test_restart_deduplication_and_original_immutability(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            history = History(path)
            archive = Archive(history.connection)
            g = Game()
            g.new_hand()
            o = Reader().read(render(g))
            profiles = [Profile(i) for i in range(6)]
            archive.save("first", o, g.events, profiles)
            archive.save("first", o, g.events, profiles)
            changed = replace(o, hole=("As", "Ah"))
            archive.save_scenario("first", 1, 2, changed, {"1": "QQ+"})
            history.close()
            history = History(path)
            archive = Archive(history.connection)
            self.assertEqual(archive.hands()[0].count, 1)
            original = archive.snapshots("first", 1)[0]
            self.assertEqual(original.observation, o)
            self.assertEqual(original.profiles, tuple(profiles))
            self.assertEqual(archive.scenario("first", 1, 2)["ranges"], {"1": "QQ+"})
            archive.reset_scenario("first", 1, 2)
            self.assertIsNone(archive.scenario("first", 1, 2))
            self.assertEqual(archive.snapshots("first", 1)[0].observation, o)
            history.close()

    def test_additive_migration_and_session_separation(self):
        history = History()
        history.record("legacy", 1, ())
        archive = Archive(history.connection)
        self.assertEqual(archive.hands(), [])
        g = Game()
        g.new_hand()
        o = Reader().read(render(g))
        for session in ("a", "b"):
            archive.save(session, o, g.events, [Profile(i) for i in range(6)])
        self.assertEqual(len(archive.hands()), 2)
        self.assertEqual(history.profile(1).hands, 0)
        history.close()

    def test_complete_replay_keeps_historical_profiles(self):
        history = History()
        archive = Archive(history.connection)
        g, reader = Game(), Reader()
        g.new_hand()
        while True:
            o = reader.read(render(g))
            history.record("session", o.hand, g.events)
            archive.save("session", o, tuple(g.events), [history.profile(i) for i in range(6)])
            if g.actor < 0:
                break
            g.act("K" if g.legal()["check"] else "C")
        self.assertTrue(archive.hands()[0].completed)
        snapshots = archive.snapshots("session", 1)
        self.assertEqual(snapshots[-1].observation.street, "X")
        self.assertEqual(len(snapshots[-1].observation.board), 5)
        self.assertEqual(snapshots[0].profiles[0].hands, 0)
        self.assertEqual(history.profile(0).hands, 1)
        self.assertEqual(snapshots[-1].events, tuple(g.events))
        history.close()
