"""Weighted eval scoring: score runs against eval points, gate on scores."""
from baremetal_harness.agent.loop import RunResult
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.evals.assertions import evaluate_assertion
from baremetal_harness.meta.evolve import GateDecision
from baremetal_harness.meta.tasks import EvalPoint, EvolutionTask, TaskScore


def score_run(task: EvolutionTask, result: RunResult) -> TaskScore:
    """逐评测点打分，加权归一化 0..1。

    task.points 空 → 二元退化（COMPLETED=1.0 / 其他=0.0），向后兼容。
    断言用机械 evaluate_assertion（7 种），不做 LLM-judge。
    """
    if not task.points:
        passed = result.status is RunStatus.COMPLETED
        return TaskScore(task.task_id, (), 1.0 if passed else 0.0)
    results: list[tuple[str, bool]] = []
    total = 0.0
    earned = 0.0
    for point in task.points:
        passed = evaluate_assertion(point.assertion, result) is None
        results.append((point.dimension, passed))
        total += point.weight
        if passed:
            earned += point.weight
    return TaskScore(task.task_id, tuple(results), earned / total if total else 0.0)


def weighted_gate(
    baseline: dict[str, float],
    candidate: dict[str, float],
) -> GateDecision:
    """preserve-and-extend 分数版：无任务分数回退 + ≥1 任务分数提升。

    分数是确定性算术，< / > 精确比较安全。旧布尔 gate 保留，本函数是分数线。
    调用方负责把 held-out（人配）与 self-mined（自挖）套件拆开喂——held-out 子集必须
    不回退，self-mined 子集可放宽（反 Goodhart，见设计文档 §一.9 洞察 2）。
    """
    regressed = [
        t for t, s in baseline.items() if candidate.get(t, 0.0) < s
    ]
    improved = [
        t for t, s in baseline.items() if candidate.get(t, 0.0) > s
    ]
    if regressed:
        return GateDecision(False, f"score regressed: {', '.join(sorted(regressed))}")
    if not improved:
        return GateDecision(False, "no task score improved")
    return GateDecision(True, f"score improved: {', '.join(sorted(improved))}")


def heuristic_weights(
    scores: tuple[TaskScore, ...],
    base: dict[str, float] | None = None,
) -> dict[str, float]:
    """启发式权重（档2）：weight = base(默认1.0) × (1 + 失败率)。

    失败率 = 该 dimension 失败次数 / 出现次数。确定性，无 LLM，无训练回路。
    base 只覆盖出现的维度；未出现维度不出权重。
    饱和维度（0 失败率）权重 = base 不浮。
    """
    base = base or {}
    occurrences: dict[str, int] = {}
    failures: dict[str, int] = {}
    for score in scores:
        for dimension, passed in score.point_results:
            occurrences[dimension] = occurrences.get(dimension, 0) + 1
            if not passed:
                failures[dimension] = failures.get(dimension, 0) + 1
    weights: dict[str, float] = {}
    for dimension, occ in occurrences.items():
        rate = failures.get(dimension, 0) / occ
        weights[dimension] = base.get(dimension, 1.0) * (1.0 + rate)
    return weights


def cap_points(
    points: tuple[EvalPoint, ...],
    max_points: int = 5,
) -> tuple[EvalPoint, ...]:
    """硬上限：评测点过多→结果不准确（Goodhart）。

    按权重降序截断，平局按维度名字典序（保证确定）。len <= max_points 原样返回。
    """
    if len(points) <= max_points:
        return points
    return tuple(sorted(points, key=lambda p: (-p.weight, p.dimension))[:max_points])
