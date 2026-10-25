from pathlib import Path

import pytest

from baremetal_harness.evals.loader import EvalLoadError, load_eval_cases


def test_loader_reads_json_cases(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        """[
          {
            "id": "simple-answer",
            "prompt": "say ok",
            "script": [{"type": "text", "text": "ok"}, {"type": "complete", "reason": "stop"}],
            "assertions": [{"type": "output_equals", "value": "ok"}]
          }
        ]"""
    )
    assert load_eval_cases(path)[0].case_id == "simple-answer"


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    case = {
        "id": "duplicate",
        "prompt": "x",
        "script": [{"type": "complete", "reason": "stop"}],
        "assertions": [{"type": "status_equals", "value": "completed"}],
    }
    import json

    path.write_text(json.dumps([case, case]))
    with pytest.raises(EvalLoadError, match="duplicate"):
        load_eval_cases(path)


def test_loader_rejects_unsourced_assertion_kinds(tmp_path: Path) -> None:
    import json

    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "unsourced",
                    "prompt": "x",
                    "script": [{"type": "complete", "reason": "stop"}],
                    "assertions": [
                        {"type": "sandbox_violation_count", "value": 0}
                    ],
                }
            ]
        )
    )
    with pytest.raises(EvalLoadError, match="unknown eval assertion"):
        load_eval_cases(path)
