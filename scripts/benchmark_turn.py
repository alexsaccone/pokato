"""Reproduce bounded turn analysis diagnostics; never reports playing strength."""
import argparse
import json
from pathlib import Path
from pokato.analysis.turn_benchmark import benchmark_case, fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("all", *fixtures()), default="all")
    parser.add_argument("--draws", type=int, default=24)
    parser.add_argument("--hands", type=int, default=32)
    parser.add_argument("--reference-hands", type=int, default=64)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--output", type=Path, default=Path("artifacts/turn-benchmark.json"))
    args = parser.parse_args()
    if args.draws < 2 or args.hands < 1 or args.reference_hands < 0:
        parser.error("Need at least two draws, positive --hands and nonnegative --reference-hands")
    names = fixtures() if args.case == "all" else (args.case,)
    report = {"version": "0.4.0", "seed": args.seed,
              "limits": "Fixed synthetic fixtures; approximate policy sensitivity, no human-performance or winnings claim.",
              "cases": []}
    for name in names:
        row = benchmark_case(name, args.draws, args.hands, args.reference_hands, args.seed)
        report["cases"].append(row)
        print(f"{name}: {row['best']}, {row['nodes']} nodes; "
              f"point {row['point_seconds']:.2f}s, sensitivity {row['sensitivity_seconds']:.2f}s", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
