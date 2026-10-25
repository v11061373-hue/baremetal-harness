import argparse
from dataclasses import dataclass
from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.meta.evolve import gate, inject_rule, mine_rule
from baremetal_harness.meta.tasks import (
    EvolutionTask,
    TaskRun,
    failure_traces,
    run_task,
)


@dataclass(frozen=True, slots=True)
class EvolutionMetrics:
    task_success_rate: float
    failed_task_ids: tuple[str, ...]


def _success_rate(results: dict[str, TaskRun]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results.values() if r.passed) / len(results)


def _failed(results: dict[str, TaskRun]) -> tuple[str, ...]:
    return tuple(sorted(t for t, r in results.items() if not r.passed))


async def evolve(
    tasks: tuple[EvolutionTask, ...],
    *,
    provider,
    model: str,
    tools,
    workspace,
    limits: RunLimits,
    skills_dir: Path,
    store: SqliteMemoryStore,
    miner_client=None,
    iterations: int = 5,
    auto: bool = False,
) -> tuple[EvolutionMetrics, ...]:
    baseline: dict[str, TaskRun] = {}
    for task in tasks:
        baseline[task.task_id] = await run_task(
            task, provider=provider, model=model, tools=tools,
            workspace=workspace, limits=limits,
        )
    history = [EvolutionMetrics(_success_rate(baseline), _failed(baseline))]
    for _ in range(iterations):
        failures = failure_traces(tuple(
            run for run in baseline.values() if not run.passed
        ))
        rule = mine_rule(miner_client, failures)
        if rule is None:
            break
        candidate: dict[str, TaskRun] = {}
        for task in tasks:
            candidate[task.task_id] = await run_task(
                task, provider=provider, model=model, tools=tools,
                workspace=workspace, limits=limits,
            )
        decision = gate(
            {t: r.passed for t, r in baseline.items()},
            {t: r.passed for t, r in candidate.items()},
        )
        if not decision.promote:
            break
        if auto:
            await inject_rule(
                rule, store=store, skills_dir=skills_dir, run_id="evolve"
            )
        baseline = candidate
        history.append(EvolutionMetrics(_success_rate(baseline), _failed(baseline)))
    return tuple(history)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harness-evolve",
        description="Run the outer evolution loop over a task suite.",
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--auto",
        action="store_true",
        help="inject promoted rules (default: dry-run, report only)",
    )
    parser.parse_args()
    # 任务套件 + provider 是产品层接线（设计文档 §三 L3 defer）。核心 API 是
    # evolve()，CLI 只是薄封装，接线在真实任务套件落地时补。
    raise SystemExit(
        "harness-evolve: no task suite wired; call evolve() programmatically "
        "with a tuple[EvolutionTask, ...]"
    )
