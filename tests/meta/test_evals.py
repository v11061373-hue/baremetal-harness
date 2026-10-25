from baremetal_harness.meta.evals import eval_gate, eval_suite_manifest, mine_eval_cases
from baremetal_harness.meta.tasks import EvolutionTask, FailureTrace


class ScriptedVerifier:
    def __init__(self, decision: str | None) -> None:
        self._decision = decision

    async def verify(self, output: str, prompt: str) -> str | None:
        return self._decision


def _task(task_id: str) -> EvolutionTask:
    return EvolutionTask(task_id, f"prompt for {task_id}", ScriptedVerifier(None))


def test_mine_eval_cases_promotes_failed_tasks() -> None:
    tasks = (_task("a"), _task("b"))
    failures = (FailureTrace("b", "missing key", "RunCompleted"),)
    assert [c.task_id for c in mine_eval_cases(failures, tasks)] == ["b"]


def test_mine_eval_cases_empty_when_no_failures() -> None:
    assert mine_eval_cases((), (_task("a"),)) == ()


def test_mine_eval_cases_skips_unknown_failure() -> None:
    failures = (FailureTrace("zzz", "nope", "RunCompleted"),)
    assert mine_eval_cases(failures, (_task("a"),)) == ()


def test_eval_gate_promotes_when_suite_passes() -> None:
    assert eval_gate(("a", "b"), {"a": True, "b": True}).promote is True


def test_eval_gate_rejects_on_suite_regression() -> None:
    decision = eval_gate(("a", "b"), {"a": False, "b": True})
    assert decision.promote is False
    assert "a" in decision.reason


def test_eval_gate_promotes_empty_suite() -> None:
    assert eval_gate((), {"a": True}).promote is True


def test_eval_suite_manifest_serializes_ids_and_prompts() -> None:
    manifest = eval_suite_manifest((_task("a"), _task("b")))
    assert '"task_id"' in manifest
    assert '"a"' in manifest
    assert "prompt for b" in manifest
