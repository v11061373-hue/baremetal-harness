import json
from dataclasses import asdict
from pathlib import Path

from baremetal_harness.evals.types import EvalResult


def write_reports(results: tuple[EvalResult, ...], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "eval-report.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2)
    )
    passed = sum(result.passed for result in results)
    lines = [
        "# BareMetal Harness Eval Report",
        "",
        f"- Passed: {passed}/{len(results)}",
        "",
    ]
    for result in results:
        lines.append(
            f"## {result.case_id}: {'PASS' if result.passed else 'FAIL'}"
        )
        for failure in result.failures:
            lines.append(f"- {failure}")
        lines.append("")
    (directory / "eval-report.md").write_text("\n".join(lines))
