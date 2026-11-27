"""CRM Assistant evaluation commands.

  validate (default)  Validate the 30 selected cases and print counts and the dataset digest.
                      No settings, database, model or network.
  live                Plan a live-model run (preview, no calls). With --live and the opt-ins
                      described in crm_live.py, run it against a disposable local database.

The database-integration layer runs under pytest: `just crm-eval-db`.
"""

import argparse
import asyncio
import json
import os
import sys

from scripts.evaluations.crm_assistant.crm_dataset import load_crm_benchmark, summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.evaluations.crm_assistant")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("validate", help="validate the cases (default)")
    live = commands.add_parser("live", help="plan, or with --live run, real model turns")
    chosen = live.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--cases", help="comma-separated case IDs, e.g. crm001,crm095")
    chosen.add_argument("--all", action="store_true", help="every case (30 paid turns)")
    live.add_argument("--live", action="store_true", help="make the model-provider calls")
    live.add_argument("--save-answers", action="store_true", help="keep answers for review")
    args = parser.parse_args(argv)

    benchmark = load_crm_benchmark()
    if args.command in (None, "validate"):
        print(json.dumps(summary(benchmark), indent=2))
        return 0

    from scripts.evaluations.crm_assistant import crm_live

    by_id = {case.id: case for case in benchmark.cases}
    wanted = list(by_id) if args.all else [item.strip() for item in args.cases.split(",")]
    unknown = [item for item in wanted if item not in by_id]
    if unknown:
        parser.error(f"unknown case IDs: {', '.join(unknown)}")
    cases = [by_id[item] for item in wanted]
    print(json.dumps(crm_live.plan(cases), indent=2))
    if not args.live:
        print("Preview only: no model, database or network calls were made.")
        return 0
    from app.config import settings

    errors = crm_live.gate_errors(os.environ, str(settings.POSTGRES_URL))
    if errors:
        for error in errors:
            print(f"Refused: {error}", file=sys.stderr)
        return 2
    result = asyncio.run(
        crm_live.run_live(
            cases,
            server_url=os.environ[crm_live.DATABASE_ENV],
            save_answers=args.save_answers,
        )
    )
    print(json.dumps(result, indent=2))
    return 0 if result["all_planned_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
