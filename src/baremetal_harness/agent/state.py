from enum import StrEnum

from baremetal_harness.core.errors import InvariantViolation


class RunStatus(StrEnum):
    CREATED = "created"
    BUILDING_CONTEXT = "building_context"
    CALLING_MODEL = "calling_model"
    VALIDATING_TOOLS = "validating_tools"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING_TOOLS = "executing_tools"
    RECORDING_RESULTS = "recording_results"
    RECORDING_TOOL_ERROR = "recording_tool_error"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXHAUSTED = "exhausted"


ALLOWED_TRANSITIONS = {
    RunStatus.CREATED: {RunStatus.BUILDING_CONTEXT, RunStatus.CANCELLED},
    RunStatus.BUILDING_CONTEXT: {
        RunStatus.CALLING_MODEL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.CALLING_MODEL: {
        RunStatus.COMPLETED,
        RunStatus.VALIDATING_TOOLS,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.EXHAUSTED,
        RunStatus.RECORDING_RESULTS,
    },
    RunStatus.VALIDATING_TOOLS: {
        RunStatus.AWAITING_APPROVAL,
        RunStatus.EXECUTING_TOOLS,
        RunStatus.RECORDING_TOOL_ERROR,
        RunStatus.CANCELLED,
    },
    RunStatus.AWAITING_APPROVAL: {
        RunStatus.EXECUTING_TOOLS,
        RunStatus.RECORDING_TOOL_ERROR,
        RunStatus.CANCELLED,
    },
    RunStatus.EXECUTING_TOOLS: {
        RunStatus.RECORDING_RESULTS,
        RunStatus.RECORDING_TOOL_ERROR,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.RECORDING_RESULTS: {
        RunStatus.BUILDING_CONTEXT,
        RunStatus.EXHAUSTED,
        RunStatus.CANCELLED,
    },
    RunStatus.RECORDING_TOOL_ERROR: {
        RunStatus.BUILDING_CONTEXT,
        RunStatus.EXHAUSTED,
        RunStatus.CANCELLED,
    },
}


def transition(current: RunStatus, target: RunStatus) -> RunStatus:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvariantViolation(f"illegal run transition: {current} -> {target}")
    return target
