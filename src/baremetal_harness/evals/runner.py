from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.evals.assertions import evaluate_assertion
from baremetal_harness.evals.types import EvalCase, EvalResult
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.observability.metrics import metrics_from_events


def _event(raw: dict[str, object]):
    event_type = raw.get("type")
    if event_type == "text":
        return TextDelta(str(raw.get("text", "")))
    if event_type == "complete":
        return ResponseCompleted(str(raw.get("reason", "stop")))
    if event_type == "tool_delta":
        return ToolCallDelta(
            int(raw.get("index", 0)),
            str(raw["id"]) if raw.get("id") is not None else None,
            str(raw["name"]) if raw.get("name") is not None else None,
            str(raw.get("arguments", "")),
        )
    raise ValueError("unknown script event")


class EvalRunner:
    async def run(self, case: EvalCase) -> EvalResult:
        provider = FakeModel(tuple(_event(item) for item in case.script))
        result = await AgentLoop(provider, "fake").run(case.prompt)
        failures = tuple(
            failure
            for assertion in case.assertions
            if (failure := evaluate_assertion(assertion, result)) is not None
        )
        return EvalResult(
            case.case_id,
            not failures,
            failures,
            metrics_from_events(result.events),
            result.run_id,
        )
