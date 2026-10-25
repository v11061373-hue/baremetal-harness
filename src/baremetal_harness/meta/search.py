from dataclasses import dataclass

from baremetal_harness.context.types import ContextSource
from baremetal_harness.meta.evolve import MAX_RULE_CHARS
from baremetal_harness.meta.tasks import FailureTrace


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
