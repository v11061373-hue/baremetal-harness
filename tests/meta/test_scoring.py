from baremetal_harness.agent.loop import RunResult
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.evals.types import EvalAssertion
from baremetal_harness.meta.scoring import (
    cap_points,
    heuristic_weights,
    score_run,
    weighted_gate,
)
from baremetal_harness.meta.tasks import EvalPoint, EvolutionTask, TaskScore


class _V:  # 占位 Verifier，本模块测试不触内层循环
    async def verify(self, output: str, prompt: str) -> str | None:
        return None


def _run(status: RunStatus, output: str = "") -> RunResult:
    return RunResult("rid", "sid", status, output, (), ())


def _task(*points: EvalPoint) -> EvolutionTask:
    return EvolutionTask("t", "p", _V(), points)


def test_score_run_empty_points_falls_back_to_binary() -> None:
    assert score_run(_task(), _run(RunStatus.COMPLETED)).score == 1.0
    assert score_run(_task(), _run(RunStatus.EXHAUSTED)).score == 0.0


def test_score_run_weighted_average() -> None:
    points = (
        EvalPoint("correctness", EvalAssertion("output_equals", "42"), 1.0),
        EvalPoint("format", EvalAssertion("output_equals", "NOPE"), 3.0),
    )
    score = score_run(_task(*points), _run(RunStatus.COMPLETED, "42"))
    assert score.score == 0.25  # 1 / (1+3)


def test_score_run_all_pass_and_all_fail() -> None:
    ok = EvalPoint("c", EvalAssertion("output_equals", "42"), 1.0)
    assert score_run(_task(ok), _run(RunStatus.COMPLETED, "42")).score == 1.0
    assert score_run(_task(ok), _run(RunStatus.COMPLETED, "x")).score == 0.0


def test_score_run_records_per_point_results() -> None:
    ok = EvalPoint("c", EvalAssertion("output_equals", "42"), 1.0)
    bad = EvalPoint("f", EvalAssertion("output_equals", "NOPE"), 1.0)
    score = score_run(_task(ok, bad), _run(RunStatus.COMPLETED, "42"))
    assert score.point_results == (("c", True), ("f", False))


def test_weighted_gate_promotes_on_improvement() -> None:
    assert weighted_gate({"a": 0.5}, {"a": 0.8}).promote is True


def test_weighted_gate_rejects_on_regression() -> None:
    d = weighted_gate({"a": 0.8, "b": 0.9}, {"a": 0.5, "b": 0.9})
    assert d.promote is False and "a" in d.reason


def test_weighted_gate_rejects_when_no_improvement() -> None:
    d = weighted_gate({"a": 0.5}, {"a": 0.5})
    assert d.promote is False and "improved" in d.reason


def test_heuristic_weights_failure_frequency() -> None:
    scores = (
        TaskScore("t1", (("c", True), ("f", False)), 0.5),
        TaskScore("t2", (("c", False), ("f", False)), 0.0),
    )
    weights = heuristic_weights(scores)
    assert weights["c"] == 1.5   # 1 × (1 + 1/2)
    assert weights["f"] == 2.0   # 1 × (1 + 2/2)


def test_heuristic_weights_base_override() -> None:
    scores = (TaskScore("t1", (("c", False),), 0.0),)
    weights = heuristic_weights(scores, base={"c": 2.0})
    assert weights["c"] == 4.0   # 2 × (1 + 1/1)


def test_heuristic_weights_empty() -> None:
    assert heuristic_weights(()) == {}


def test_evolution_task_points_default() -> None:
    assert EvolutionTask("t", "p", _V()).points == ()


def test_cap_points_noop_under_limit() -> None:
    pts = (EvalPoint("a", EvalAssertion("output_equals", "1")),)
    assert cap_points(pts, max_points=5) == pts


def test_cap_points_truncates_by_weight() -> None:
    hi = EvalPoint("hi", EvalAssertion("output_equals", "1"), 3.0)
    lo = EvalPoint("lo", EvalAssertion("output_equals", "2"), 1.0)
    mid = EvalPoint("mid", EvalAssertion("output_equals", "3"), 2.0)
    pts = (lo, mid, hi)
    assert cap_points(pts, max_points=2) == (hi, mid)  # 权重降序，去掉 lo


def test_cap_points_tiebreak_by_dimension_name() -> None:
    b = EvalPoint("b", EvalAssertion("output_equals", "1"), 1.0)
    a = EvalPoint("a", EvalAssertion("output_equals", "2"), 1.0)
    c = EvalPoint("c", EvalAssertion("output_equals", "3"), 1.0)
    assert cap_points((b, a, c), max_points=2) == (a, b)  # 平局字典序
