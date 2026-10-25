from dataclasses import dataclass
from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.context.types import ContextSource
from baremetal_harness.meta.evolve import MAX_RULE_CHARS, build_rule_skill
from baremetal_harness.meta.scoring import score_run, weighted_gate
from baremetal_harness.meta.tasks import (
    EvolutionTask,
    FailureTrace,
    TaskRun,
    failure_traces,
    run_task,
)


@dataclass(frozen=True, slots=True)
class ScaffoldState:
    """训练回路可改的脚手架状态 = rules。eval cases 是 ground truth，不进这里。"""

    rules: tuple[str, ...] = ()


class RulesProvider:
    """把候选 rules 注入 run 的 ContextProvider。"""

    def __init__(self, rules: tuple[str, ...]) -> None:
        self.rules = rules

    async def build(self, prompt: str) -> tuple[ContextSource, ...]:
        if not self.rules:
            return ()
        body = "\n".join(f"- {rule}" for rule in self.rules)
        return (ContextSource("harness-rules", body, 90, required=True),)


def propose_candidates(
    state: ScaffoldState,
    failures: tuple[FailureTrace, ...],
) -> tuple[ScaffoldState, ...]:
    """机械突变：从失败 reason 切规则候选，粒度 1/2/3 条各一（分支宽度 N≤3）。"""
    if not failures:
        return ()
    reasons = [f.reason for f in failures[:3]]
    return tuple(
        ScaffoldState((*state.rules, " ".join(reasons[:n])[:MAX_RULE_CHARS]))
        for n in range(1, len(reasons) + 1)
    )


async def evaluate_state(
    state: ScaffoldState,
    tasks: tuple[EvolutionTask, ...],
    *,
    provider,
    model: str,
    tools,
    workspace,
    limits: RunLimits,
) -> tuple[TaskRun, ...]:
    """离线评测：注入 state.rules → run_task，返回 TaskRun（含 RunResult）。"""
    return tuple([
        await run_task(
            task, provider=provider, model=model, tools=tools,
            workspace=workspace, limits=limits,
            context_providers=(RulesProvider(state.rules),),
        )
        for task in tasks
    ])


@dataclass(frozen=True, slots=True)
class SearchStep:
    scores: dict[str, float]
    promoted: ScaffoldState | None


async def branch_search(
    tasks: tuple[EvolutionTask, ...],
    *,
    provider,
    model: str,
    tools,
    workspace,
    limits: RunLimits,
    initial: ScaffoldState | None = None,
    iterations: int = 5,
) -> tuple[SearchStep, ...]:
    """沙箱分支搜索：propose → evaluate → weighted_gate → 选最优 promote。"""
    current = initial if initial is not None else ScaffoldState()
    steps: list[SearchStep] = []
    for _ in range(iterations):
        runs = await evaluate_state(
            current, tasks, provider=provider, model=model, tools=tools,
            workspace=workspace, limits=limits,
        )
        scores = {
            t.task_id: score_run(t, r.result).score
            for t, r in zip(tasks, runs, strict=True)
        }
        failures = failure_traces(tuple(r for r in runs if not r.passed))
        best: ScaffoldState | None = None
        best_scores = scores
        for candidate in propose_candidates(current, failures):
            cruns = await evaluate_state(
                candidate, tasks, provider=provider, model=model, tools=tools,
                workspace=workspace, limits=limits,
            )
            cscores = {
                t.task_id: score_run(t, r.result).score
                for t, r in zip(tasks, cruns, strict=True)
            }
            if (
                weighted_gate(scores, cscores).promote
                and sum(cscores.values()) > sum(best_scores.values())
            ):
                best, best_scores = candidate, cscores
        if best is None:
            steps.append(SearchStep(scores, None))
            break
        steps.append(SearchStep(best_scores, best))
        current = best
    return tuple(steps)


def promote_state(state: ScaffoldState, *, skills_dir: Path) -> None:
    """原子写回：rules → skills_dir/harness-rules/SKILL.md（复用 build_rule_skill）。"""
    path = skills_dir / "harness-rules" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_rule_skill(state.rules), encoding="utf-8")
