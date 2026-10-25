from dataclasses import dataclass


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
