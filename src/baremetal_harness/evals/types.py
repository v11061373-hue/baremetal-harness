from dataclasses import dataclass

from baremetal_harness.observability.types import RunMetrics


@dataclass(frozen=True, slots=True)
class EvalAssertion:
    kind: str
    expected: object


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    prompt: str
    script: tuple[dict[str, object], ...]
    assertions: tuple[EvalAssertion, ...]
    fault_plan: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class EvalResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...]
    metrics: RunMetrics
    run_id: str
