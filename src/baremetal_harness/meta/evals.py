"""Regression eval suite: mine failures into cases, gate against accumulation."""
import json

from baremetal_harness.meta.evolve import GateDecision
from baremetal_harness.meta.tasks import EvolutionTask, FailureTrace


def mine_eval_cases(
    failures: tuple[FailureTrace, ...],
    tasks: tuple[EvolutionTask, ...],
) -> tuple[EvolutionTask, ...]:
    """机械挖掘：失败 task 提升为回归评测用例（prompt+verifier 复用原 task）。

    无 LLM——把「失败」本身当用例，下一轮必须不再失败。声明式 `evals/`
    走 FakeModel 脚本化回放，真 run 失败无 script 可回放，故本套件 meta 原生。
    """
    failed = {f.task_id for f in failures}
    return tuple(t for t in tasks if t.task_id in failed)


def eval_gate(
    suite: tuple[str, ...],
    candidate: dict[str, bool],
) -> GateDecision:
    """评测门控：候选不得让 suite 中任何回归用例回退（无转成功要求，区别于 gate）。"""
    regressed = [t for t in suite if not candidate.get(t, False)]
    if regressed:
        return GateDecision(False, f"eval regression: {', '.join(sorted(regressed))}")
    return GateDecision(True, "no eval regression")


def eval_suite_manifest(cases: tuple[EvolutionTask, ...]) -> str:
    """套件 manifest（进 git 版本化）。verifier 闭包不序列化，只记 id+prompt。"""
    return json.dumps(
        [{"task_id": c.task_id, "prompt": c.prompt} for c in cases],
        ensure_ascii=False,
        indent=2,
    )
