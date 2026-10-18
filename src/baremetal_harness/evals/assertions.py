from baremetal_harness.agent.loop import RunResult
from baremetal_harness.evals.types import EvalAssertion


def evaluate_assertion(
    assertion: EvalAssertion,
    result: RunResult,
) -> str | None:
    if assertion.kind == "output_equals":
        actual = result.output
    elif assertion.kind == "status_equals":
        actual = result.status.value
    elif assertion.kind == "event_sequence_contains":
        actual = [event.payload.__class__.__name__ for event in result.events]
        expected = assertion.expected
        if not isinstance(expected, list) or not all(
            item in actual for item in expected
        ):
            return "event sequence does not contain expected event types"
        return None
    else:
        return f"assertion kind is not supported by this runner: {assertion.kind}"
    if actual != assertion.expected:
        return f"{assertion.kind} expected {assertion.expected!r}, got {actual!r}"
    return None
