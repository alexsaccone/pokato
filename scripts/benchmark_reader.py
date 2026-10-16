"""Held-out values on two synthetic calibrated skins; not real-client accuracy."""
import argparse
import json
from pathlib import Path
import statistics
import time
from PIL import Image, ImageDraw
from pokato.core.game import Game
from pokato.vision.calibrated import CalibratedReader
from pokato.vision.fixtures import SyntheticSkin, from_game
from pokato.vision.sources import Frame


def benchmark(frames=12, seed=31):
    game = Game(seed)
    game.new_hand()
    snapshots = []
    while game.street != "X":
        snapshots.append(from_game(game, len(snapshots)))
        legal = game.legal()
        game.act("R", legal["min_raise"]) if len(snapshots) in (3, 10, 16) and legal["min_raise"] else game.act("K" if legal["check"] else "C")
    selected = [snapshots[round(i*(len(snapshots)-1)/max(1, frames-1))] for i in range(frames)]
    report = {"scope": "synthetic calibrated skins; unseen values, not unseen fonts or real-client accuracy", "seed": seed, "skins": []}
    for style in ("wide", "tall"):
        skin = SyntheticSkin(style)
        reader = CalibratedReader(skin.train())
        accepted = correct = rejected = total = 0
        latencies = []
        for truth in selected:
            original = skin.render(truth)
            for scale in (1., 1.5, 2.):
                image = original.resize(tuple(round(n*scale) for n in original.size), Image.Resampling.NEAREST)
                started = time.perf_counter()
                result = reader.read(Frame(image, truth.index, truth.timestamp, style))
                latencies.append(1000*(time.perf_counter()-started))
                total += 1
                if result.snapshot:
                    accepted += 1
                    actual = result.snapshot
                    correct += (actual.hole, actual.board, actual.pot, actual.actor, actual.button,
                                tuple((s.status, s.stack, s.bet) for s in actual.seats)) == (
                                    truth.hole, truth.board, truth.pot, truth.actor, truth.button,
                                    tuple((s.status, s.stack, s.bet) for s in truth.seats))
            for field, color in (("anchor", "red"), ("pot", "#182535")):
                bad = original.copy()
                ImageDraw.Draw(bad).rectangle(skin.boxes[field], fill=color)
                rejected += reader.read(Frame(bad, truth.index, truth.timestamp, "occluded")).snapshot is None
        ordered = sorted(latencies)
        report["skins"].append({"style": style, "valid_frames": total, "accepted": accepted,
                                "fully_correct": correct, "corrupt_frames": 2*frames, "corrupt_rejected": rejected,
                                "median_ms": round(statistics.median(ordered), 1),
                                "p95_ms": round(ordered[min(len(ordered)-1, round(.95*(len(ordered)-1)))] , 1)})
    report["ok"] = all(row["fully_correct"] == row["valid_frames"] and row["corrupt_rejected"] == row["corrupt_frames"] for row in report["skins"])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--output", type=Path, default=Path("artifacts/reader-benchmark.json"))
    args = parser.parse_args()
    if not 2 <= args.frames <= 100:
        parser.error("--frames must be between 2 and 100")
    report = benchmark(args.frames, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)
