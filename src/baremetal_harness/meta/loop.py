import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.evals.types import EvalAssertion
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.meta.evolve import gate, inject_rule, mine_rule
from baremetal_harness.meta.tasks import (
    EvalPoint,
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


def _verifier(assertion: EvalAssertion):
    class _V:
        async def verify(self, output: str, prompt: str) -> str | None:
            if assertion.kind != "output_equals":
                return f"verifier DSL unsupported kind: {assertion.kind}"
            if output != assertion.expected:
                return (
                    f"output_equals expected {assertion.expected!r}, got {output!r}"
                )
            return None

    return _V()


def parse_suite(path: Path) -> tuple[EvolutionTask, ...]:
    """套件 JSON → EvolutionTask。verifier 只认 output_equals，points 走全断言。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for raw in data["tasks"]:
        verifier = EvalAssertion(raw["verifier"]["kind"], raw["verifier"]["expected"])
        points = tuple(
            EvalPoint(
                p["dimension"],
                EvalAssertion(p["assertion"]["kind"], p["assertion"]["expected"]),
                float(p.get("weight", 1.0)),
            )
            for p in raw.get("points", ())
        )
        tasks.append(
            EvolutionTask(raw["task_id"], raw["prompt"], _verifier(verifier), points)
        )
    return tuple(tasks)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harness-evolve",
        description="Run the outer evolution loop over a task suite.",
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--suite", type=Path, default=None, help="task suite JSON")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="inject promoted rules (default: dry-run, report only)",
    )
    args = parser.parse_args()
    if args.suite is None:
        # 真 provider 接线是产品层（设计文档 §三 L3 defer）。核心 API 是
        # evolve()/branch_search()，CLI 只是薄封装。
        raise SystemExit(
            "harness-evolve: --suite PATH required (JSON task suite); call "
            "evolve()/branch_search() programmatically for full control"
        )
    tasks = parse_suite(args.suite)
    print(f"loaded {len(tasks)} tasks: {', '.join(t.task_id for t in tasks)}")
