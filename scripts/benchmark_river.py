import argparse
import json
from pathlib import Path
from pokato.analysis.benchmark import benchmark


def main():
    parser = argparse.ArgumentParser(description="Paired synthetic river strategy and session-adaptation benchmark")
    parser.add_argument("--pairs", type=int, default=400)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--output", type=Path, default=Path("artifacts/river-benchmark.json"))
    args = parser.parse_args()
    report = benchmark(args.pairs, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
