"""Outer evolution loop (run-mine-gate-inject) + regression eval suite."""

from baremetal_harness.meta.evals import (
    eval_gate,
    eval_suite_manifest,
    mine_eval_cases,
)
from baremetal_harness.meta.evolve import (
    GateDecision,
    build_rule_skill,
    gate,
    inject_rule,
    mine_rule,
    mine_rule_llm,
)
from baremetal_harness.meta.loop import EvolutionMetrics, evolve
from baremetal_harness.meta.scoring import (
    cap_points,
    heuristic_weights,
    score_run,
    weighted_gate,
)
from baremetal_harness.meta.search import (
    RulesProvider,
    ScaffoldState,
    SearchStep,
    branch_search,
    evaluate_state,
    promote_state,
    propose_candidates,
)
from baremetal_harness.meta.tasks import (
    EvalPoint,
    EvolutionTask,
    FailureTrace,
    TaskRun,
    TaskScore,
    failure_traces,
    run_task,
)

__all__ = [
    "EvolutionTask",
    "EvalPoint",
    "TaskScore",
    "TaskRun",
    "FailureTrace",
    "run_task",
    "failure_traces",
    "evolve",
    "EvolutionMetrics",
    "mine_rule",
    "mine_rule_llm",
    "gate",
    "GateDecision",
    "build_rule_skill",
    "inject_rule",
    "score_run",
    "weighted_gate",
    "heuristic_weights",
    "cap_points",
    "ScaffoldState",
    "RulesProvider",
    "propose_candidates",
    "evaluate_state",
    "SearchStep",
    "branch_search",
    "promote_state",
    "mine_eval_cases",
    "eval_gate",
    "eval_suite_manifest",
]
