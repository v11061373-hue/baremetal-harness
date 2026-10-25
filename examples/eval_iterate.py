"""评测迭代外循环，离线可跑：run → mine → gate → inject → eval。

展示 baremetal_harness.meta 的评测迭代原语：
EvolutionTask + Verifier → run_task → failure_traces → mine_rule →
gate（promote-and-extend）→ inject_rule（SKILL.md + 记忆沉淀）→
mine_eval_cases → eval_gate → eval_suite_manifest。

运行：uv run python examples/eval_iterate.py
"""

import asyncio
import tempfile
from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.meta import (
    EvolutionTask,
    eval_gate,
    eval_suite_manifest,
    failure_traces,
    gate,
    inject_rule,
    mine_eval_cases,
    mine_rule,
    run_task,
)
from baremetal_harness.model.fake import FakeModel


class CheckContains:
    """Verifier：输出必须含 needle，否则返回失败原因。"""

    def __init__(self, needle: str) -> None:
        self._needle = needle

    async def verify(self, output: str, prompt: str) -> str | None:
        if self._needle in output:
            return None
        return f"output missing {self._needle!r}"


async def main() -> None:
    provider = FakeModel(
        [TextDelta("the answer is 42"), ResponseCompleted("stop")]
    )
    limits = RunLimits(2, 2)
    tasks = (
        EvolutionTask("math", "what is 6*7", CheckContains("42")),
        EvolutionTask("poem", "write a poem", CheckContains("definitely-not-there")),
    )

    runs = {
        t.task_id: await run_task(
            t, provider=provider, model="fake", tools=None, workspace=None, limits=limits
        )
        for t in tasks
    }

    print("== run ==")
    for task_id, run in runs.items():
        print(f"  {task_id}: passed={run.passed}")

    failures = failure_traces(tuple(r for r in runs.values() if not r.passed))
    rule = mine_rule(None, failures)
    print("== mine ==")
    print(f"  rule={rule!r}")

    baseline = {t: r.passed for t, r in runs.items()}
    candidate = {**baseline, "poem": True}  # 假设挖出的规则修好了 poem
    print("== gate ==")
    print(f"  decision={gate(baseline, candidate)}")

    # inject：把挖出的规则写进 SKILL.md + 沉淀到记忆（模块 2 store.add）
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "skills"
        store = SqliteMemoryStore(Path(tmp) / "state.db", Path(tmp) / "src")
        await store.initialize()
        await inject_rule(rule, store=store, skills_dir=skills, run_id="demo")
        print("== inject ==")
        print((skills / "harness-rules" / "SKILL.md").read_text().rstrip())

    cases = mine_eval_cases(failures, tasks)
    print("== eval ==")
    print(f"  cases={[c.task_id for c in cases]}")
    suite = tuple(c.task_id for c in cases)
    print(f"  eval_gate={eval_gate(suite, candidate)}")
    print(eval_suite_manifest(cases))


if __name__ == "__main__":
    asyncio.run(main())
