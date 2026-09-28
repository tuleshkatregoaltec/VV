"""Read-only benchmark and capability discovery commands."""

import argparse
import json

from scripts.evaluation.dataset import load_benchmark
from scripts.evaluation.inventory import build_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "dataset"])
    args = parser.parse_args()
    if args.command == "inventory":
        result = build_inventory()
    else:
        benchmark = load_benchmark()
        result = {"sha256": benchmark.digest, **benchmark.model_dump()}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
