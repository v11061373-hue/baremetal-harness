from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.loop import RunResult
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.meta.tasks import (
    EvolutionTask,
    TaskRun,
    failure_traces,
    run_task,
)
from baremetal_harness.model.fake import FakeModel


class ScriptedVerifier:
    def __init__(self, decision: str | None) -> None:
        self._decision = decision

    async def verify(self, output: str, prompt: str) -> str | None:
        return self._decision


async def test_run_task_passes_when_verifier_passes() -> None:
    task = EvolutionTask("t1", "do", ScriptedVerifier(None))
    run = await run_task(
        task,
        provider=FakeModel([TextDelta("ok"), ResponseCompleted("stop")]),
        model="fake",
        tools=None,
        workspace=None,
        limits=RunLimits(2, 2),
    )
    assert run.passed is True


async def test_run_task_fails_when_verifier_fails() -> None:
    task = EvolutionTask("t1", "do", ScriptedVerifier("no config"))
    run = await run_task(
        task,
        provider=FakeModel([TextDelta("ok"), ResponseCompleted("stop")]),
        model="fake",
        tools=None,
        workspace=None,
        limits=RunLimits(2, 2),
    )
    assert run.passed is False


def test_failure_traces_extracts_reason() -> None:
    result = RunResult("r", "s", RunStatus.EXHAUSTED, "", (), ())
    traces = failure_traces((TaskRun("t1", False, result),))
    assert traces[0].reason == "status=exhausted"
    assert traces[0].task_id == "t1"
