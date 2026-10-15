from dataclasses import asdict
import json
import unittest
from pokato.analysis.bayes import SessionModel, ResponseCount, model_from_dict
from pokato.analysis.history import History
from pokato.core.game import Event, Game
from pokato.replay.store import Archive
from pokato.simulator.render import render
from pokato.vision.reader import Reader


class BayesTests(unittest.TestCase):
    def test_cold_start_prior_and_sparse_shrinkage(self):
        baseline = SessionModel(1).posterior("R", 50, 150)
        self.assertEqual(baseline.alpha, (10, 11, 3))
        updated = SessionModel(1, (ResponseCount("R", "medium", "F", 1),)).posterior("R", 50, 150)
        self.assertEqual(updated.alpha, (11, 11, 3))
        self.assertAlmostEqual(updated.data_weight, 1/25)
        self.assertGreater(updated.mean[0], baseline.mean[0])
        self.assertLess(updated.mean[0], .5)

    def test_context_transfer_and_uncertainty(self):
        model = SessionModel(1, (ResponseCount("F", "medium", "F", 20), ResponseCount("R", "small", "C", 8)))
        p = model.posterior("R", 50, 150)
        self.assertEqual(p.alpha, (12, 13, 3))
        self.assertEqual((p.local, p.other), (0, 28))
        low, high = p.interval("F")
        self.assertLess(low, p.mean[0])
        self.assertGreater(high, p.mean[0])
        self.assertEqual(model_from_dict(asdict(model)), model)

    def test_session_isolation_and_capture_deduplication(self):
        history = History()
        events = (Event(1, 1, "P", "B", 5), Event(2, 2, "P", "B", 10), Event(3, 1, "P", "F", 0))
        history.record("old", 1, events)
        self.assertEqual(history.session_model("new", 1).opportunities, 0)
        self.assertEqual(history.profile(1, "new").hands, 0)
        for _ in range(3):
            history.record("new", 1, events)
        self.assertEqual(history.session_model("new", 1).opportunities, 1)
        self.assertEqual(history.profile(1, "new").hands, 1)
        history.close()

    def test_archived_model_does_not_see_later_evidence(self):
        history = History()
        game = Game()
        game.new_hand()
        archive = Archive(history.connection)
        o = Reader().read(render(game))
        models = tuple(history.session_model("a", i) for i in range(6))
        archive.save("a", o, game.events, [history.profile(i, "a") for i in range(6)], models)
        history.record("a", 2, (Event(1, 1, "R", "R", 20),))
        self.assertEqual(archive.snapshots("a", 1)[0].models, models)
        self.assertEqual(history.session_model("a", 1).opportunities, 1)
        # Older snapshot payloads remain readable and use baseline responses.
        row = history.connection.execute("SELECT payload FROM replay_snapshots").fetchone()
        data = json.loads(row[0])
        data["version"] = 1
        data.pop("models")
        history.connection.execute("UPDATE replay_snapshots SET payload=?", (json.dumps(data),))
        self.assertEqual(archive.snapshots("a", 1)[0].models, ())
        history.close()

    def test_invalid_model_payloads_rejected(self):
        for street, bucket, action in (("", "medium", "F"), ("Z", "small", "C"),
                                        ("R", "open", "F"), ("R", "unknown", "R")):
            data = asdict(SessionModel(1, (ResponseCount(street, bucket, action, 1),)))
            with self.subTest(data=data), self.assertRaises(ValueError):
                model_from_dict(data)
