import argparse
import asyncio
from pathlib import Path

from baremetal_harness.evals.loader import load_eval_cases
from baremetal_harness.evals.report import write_reports
from baremetal_harness.evals.runner import EvalRunner


async def run(path: Path, output: Path) -> int:
    runner = EvalRunner()
    results = tuple([await runner.run(case) for case in load_eval_cases(path)])
    write_reports(results, output)
    return 0 if all(result.passed for result in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run",))
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("."))
    args = parser.parse_args()
    return asyncio.run(run(args.path, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
