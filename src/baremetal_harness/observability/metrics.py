from baremetal_harness.agent.loop import (
    ApprovalRequested,
    ApprovalResolved,
    ModelStreamStarted,
    RunCompleted,
)
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.observability.types import RunMetrics


def metrics_from_events(events: tuple[EventEnvelope, ...]) -> RunMetrics:
    resolutions = [
        event.payload
        for event in events
        if isinstance(event.payload, ApprovalResolved)
    ]
    return RunMetrics(
        model_requests=sum(
            isinstance(event.payload, ModelStreamStarted) for event in events
        ),
        input_tokens=None,
        output_tokens=None,
        approval_requested=sum(
            isinstance(event.payload, ApprovalRequested) for event in events
        ),
        approval_approved=sum(item.approved for item in resolutions),
        approval_denied=sum(not item.approved for item in resolutions),
        final_status=(
            "completed"
            if any(isinstance(event.payload, RunCompleted) for event in events)
            else None
        ),
    )
