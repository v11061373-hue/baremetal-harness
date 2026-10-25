import json
import sys

from baremetal_harness.evals.types import EvalAssertion
from baremetal_harness.meta.loop import main, parse_suite


async def test_parse_suite(tmp_path) -> None:
    suite = {
        "tasks": [
            {
                "task_id": "math",
                "prompt": "6*7",
                "verifier": {"kind": "output_equals", "expected": "42"},
                "points": [
                    {
                        "dimension": "correctness",
                        "assertion": {"kind": "output_equals", "expected": "42"},
                        "weight": 1.0,
                    }
                ],
            }
        ]
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    tasks = parse_suite(path)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "math"
    assert task.prompt == "6*7"
    assert len(task.points) == 1
    assert task.points[0].dimension == "correctness"
    assert task.points[0].assertion == EvalAssertion("output_equals", "42")
    assert await task.verifier.verify("42", "") is None
    assert await task.verifier.verify("6", "") is not None


def test_main_loads_suite(tmp_path, monkeypatch, capsys) -> None:
    suite = {
        "tasks": [
            {
                "task_id": "math",
                "prompt": "6*7",
                "verifier": {"kind": "output_equals", "expected": "42"},
            }
        ]
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["harness-evolve", "--suite", str(path)])
    main()  # 不抛 SystemExit
    assert "math" in capsys.readouterr().out
