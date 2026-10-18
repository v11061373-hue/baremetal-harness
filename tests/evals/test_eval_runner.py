from pathlib import Path

from baremetal_harness.evals.loader import load_eval_cases
from baremetal_harness.evals.report import write_reports
from baremetal_harness.evals.runner import EvalRunner
from baremetal_harness.evals.types import EvalAssertion, EvalCase


async def test_runner_executes_scripted_answer() -> None:
    case = EvalCase(
        "simple-answer",
        "say ok",
        (
            {"type": "text", "text": "ok"},
            {"type": "complete", "reason": "stop"},
        ),
        (
            EvalAssertion("output_equals", "ok"),
            EvalAssertion("status_equals", "completed"),
        ),
    )

    result = await EvalRunner().run(case)

    assert result.passed is True
    assert result.failures == ()


async def test_core_suite_writes_both_reports(tmp_path: Path) -> None:
    cases = load_eval_cases(Path("tests/fixtures/evals/core.json"))
    results = tuple([await EvalRunner().run(case) for case in cases])

    write_reports(results, tmp_path)

    assert len(results) >= 10
    assert all(result.passed for result in results)
    assert (tmp_path / "eval-report.json").exists()
    assert (tmp_path / "eval-report.md").exists()
