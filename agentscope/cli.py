"""Offline regression replay for local development and CI."""

import argparse
import asyncio
import json
from pathlib import Path
from .demo import RunRequest, SCENARIOS, execute
from .store import Store


async def run(args):
    store = Store(":memory:")
    try:
        scenarios = list(SCENARIOS) if args.command == "check" else [args.scenario]
        rows = [
            await execute(RunRequest(scenario=s, variant=args.variant), store)
            for s in scenarios
        ]
        result = {
            "dataset": "incident-fixtures-v1",
            "runtime": "scripted",
            "passed": all(r["passed"] for r in rows),
            "rows": rows,
        }
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "passed": result["passed"],
                    "cases": len(rows),
                    "passed_cases": sum(r["passed"] for r in rows),
                    "output": args.output,
                }
            )
        )
        return 0 if result["passed"] else 1
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("replay", "check"):
        command = commands.add_parser(name)
        command.add_argument(
            "--variant", choices=["baseline", "guarded"], default="guarded"
        )
        command.add_argument("--output")
        if name == "replay":
            command.add_argument("--scenario", choices=list(SCENARIOS), required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
