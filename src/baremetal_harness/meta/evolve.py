from dataclasses import dataclass
from pathlib import Path

from baremetal_harness.memory.consolidation import MemoryCandidate
from baremetal_harness.memory.store import SqliteMemoryStore

MAX_RULE_CHARS = 2000
RULES_SKILL_NAME = "harness-rules"


@dataclass(frozen=True, slots=True)
class GateDecision:
    promote: bool
    reason: str


def gate(baseline: dict[str, bool], candidate: dict[str, bool]) -> GateDecision:
    """preserve-and-extend：无已过任务回退 + 至少一个失败转成功。"""
    broken = [
        t for t, ok in baseline.items() if ok and not candidate.get(t, False)
    ]
    gained = [
        t for t, ok in baseline.items() if not ok and candidate.get(t, False)
    ]
    if broken:
        return GateDecision(False, f"regressed: {', '.join(sorted(broken))}")
    if not gained:
        return GateDecision(False, "no failing task converted")
    return GateDecision(True, f"converted: {', '.join(sorted(gained))}")


def build_rule_skill(rules: tuple[str, ...]) -> str:
    """生成 SKILL.md 文本（always-on 规则 skill，triggers 空）。"""
    body = "\n".join(f"- {rule}" for rule in rules)
    return (
        "---\n"
        "name: harness-rules\n"
        "description: Accumulated rules mined from failed runs\n"
        "triggers:\n"
        "---\n"
        f"{body}\n"
    )


def _append_rule(existing: str, rule: str) -> str:
    return existing.rstrip("\n") + f"\n- {rule}\n"


async def inject_rule(
    rule: str,
    *,
    store: SqliteMemoryStore,
    skills_dir: Path,
    run_id: str,
) -> None:
    """写 SKILL.md + 沉淀失败教训到 memory（模块 2 的 store.add）。"""
    path = skills_dir / RULES_SKILL_NAME / "SKILL.md"
    existing = (
        path.read_text(encoding="utf-8")
        if path.is_file()
        else build_rule_skill(())
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_append_rule(existing, rule), encoding="utf-8")
    await store.add(
        MemoryCandidate(
            f"mined rule: {rule}",
            f"run:{run_id}:tool:evolve",
            ("outcome:failed",),
            None,
        )
    )
