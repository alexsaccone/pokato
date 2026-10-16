"""Measure a saved reader profile against manually labeled, held-out frames.

Manifest v1: {"version": 1, "frames": [{"image": "relative.png",
"split": "test", "fields": {"board0.rank": "Q", "pot": "12K"}}]}.
Only test frames are scored. Images and reports remain local unless shared.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
from PIL import Image
from pokato.vision.calibrated import CalibratedReader, label_for, parse_amount
from pokato.vision.layouts import Layout
from pokato.vision.sources import Frame


def benchmark(layout, manifest, folder):
    if manifest.get("version") != 1:
        raise ValueError("Unsupported label manifest")
    reader = CalibratedReader(layout)
    totals, details, states = Counter(), [], []
    for index, row in enumerate(manifest["frames"]):
        if row.get("split") != "test":
            continue
        with Image.open(folder/row["image"]) as source:
            reading = reader.read(Frame(source.convert("RGB"), index, float(index), row["image"]))
        states.append({"image": row["image"], "complete": reading.snapshot is not None, "issues": reading.issues})
        found = {field.name: field for field in reading.fields}
        for name, text in row["fields"].items():
            region = layout.regions[name]
            expected = label_for(region.kind, text)
            if region.kind == "number":
                expected = parse_amount(expected, layout.chip_unit, layout.decimal_separator, region.multiplier)
            elif region.kind in ("flag", "anchor"):
                expected = expected in ("yes", "match")
            field = found.get(name)
            actual = field.value if field else None
            outcome = "unknown" if actual is None else "correct" if actual == expected else "wrong"
            totals[outcome] += 1
            details.append({"image": row["image"], "field": name, "expected": expected,
                            "outcome": outcome, "reading": asdict(field) if field else None})
    total = sum(totals.values())
    accepted = totals["correct"]+totals["wrong"]
    return {"layout": layout.name, "test_frames": len(states), "complete_snapshots": sum(s["complete"] for s in states),
            "labeled_fields": total, "correct": totals["correct"],
            "unknown": totals["unknown"], "wrong": totals["wrong"],
            "coverage": accepted/total if total else 0.,
            "accepted_accuracy": totals["correct"]/accepted if accepted else None,
            "states": states, "details": details}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = benchmark(Layout.load(args.layout), json.loads(args.manifest.read_text(encoding="utf-8")), args.manifest.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("details", "states")}, indent=2))
    raise SystemExit(1 if result["wrong"] or not result["labeled_fields"] else 0)
