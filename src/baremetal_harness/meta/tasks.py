from dataclasses import dataclass

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.loop import AgentLoop, RunResult, Verifier
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.evals.types import EvalAssertion
from baremetal_harness.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class EvalPoint:
    dimension: str
    assertion: EvalAssertion
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class TaskScore:
    task_id: str
    point_results: tuple[tuple[str, bool], ...]  # (dimension, passed)
    score: float                                # 0..1 归一化加权分


@dataclass(frozen=True, slots=True)
class EvolutionTask:
    task_id: str
    prompt: str
    verifier: Verifier
    points: tuple[EvalPoint, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskRun:
    task_id: str
    passed: bool
    result: RunResult


@dataclass(frozen=True, slots=True)
class FailureTrace:
    task_id: str
    reason: str
    events_text: str


async def run_task(
    task: EvolutionTask,
    *,
    provider,
    model: str,
    tools: ToolRegistry | None,
    workspace,
    limits: RunLimits,
) -> TaskRun:
    """真模型跑一个任务，pass/fail = verifier 通过/耗尽（复用模块 1 语义）。"""
    loop = AgentLoop(
        provider, model, limits=limits, tools=tools, workspace=workspace,
        verifier=task.verifier,
    )
    result = await loop.run(task.prompt)
    return TaskRun(task.task_id, result.status is RunStatus.COMPLETED, result)


def failure_traces(runs: tuple[TaskRun, ...]) -> tuple[FailureTrace, ...]:
    """从失败 run 抽 mine 原料：reason + 事件文本摘要（无 LLM）。"""
    traces = []
    for run in runs:
        if run.passed:
            continue
        failed = [
            e.payload.reason
            for e in run.result.events
            if e.payload.__class__.__name__ == "VerificationFailed"
        ]
        reason = failed[-1] if failed else f"status={run.result.status.value}"
        events_text = "\n".join(
            e.payload.__class__.__name__ for e in run.result.events[-20:]
        )
        traces.append(FailureTrace(run.task_id, reason, events_text))
    return tuple(traces)
