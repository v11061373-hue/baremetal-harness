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
)
from baremetal_harness.meta.loop import EvolutionMetrics, evolve
from baremetal_harness.meta.tasks import (
    EvolutionTask,
    FailureTrace,
    TaskRun,
    failure_traces,
    run_task,
)

__all__ = [
    "EvolutionTask",
    "TaskRun",
    "FailureTrace",
    "run_task",
    "failure_traces",
    "evolve",
    "EvolutionMetrics",
    "mine_rule",
    "gate",
    "GateDecision",
    "build_rule_skill",
    "inject_rule",
    "mine_eval_cases",
    "eval_gate",
    "eval_suite_manifest",
]
