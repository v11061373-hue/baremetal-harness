from dataclasses import dataclass
from enum import StrEnum

from baremetal_harness.core.errors import ToolNotFound
from baremetal_harness.core.messages import Message, ToolCall, ToolResultContent


class RecoveryDecision(StrEnum):
    RESUME = "resume"
    REQUIRES_APPROVAL = "requires_approval"
    UNRECOVERABLE = "unrecoverable"


@dataclass(frozen=True, slots=True)
class ToolExecutionRecord:
    tool_call_id: str
    status: str
    idempotent: bool


def decide_recovery(
    *,
    checkpoint_valid: bool,
    executions: tuple[ToolExecutionRecord, ...],
) -> RecoveryDecision:
    if not checkpoint_valid:
        return RecoveryDecision.UNRECOVERABLE
    if any(
        execution.status == "started" and not execution.idempotent
        for execution in executions
    ):
        return RecoveryDecision.REQUIRES_APPROVAL
    return RecoveryDecision.RESUME


def pending_tool_executions(
    messages: tuple[Message, ...],
    registry,
) -> tuple[ToolExecutionRecord, ...]:
    """Find tool calls a checkpoint recorded without a matching result.

    A crash between dispatching a tool and recording its result leaves exactly
    this gap, so the message history is the authoritative source: any state the
    process meant to write about the call may itself have been lost.
    """
    started: dict[str, str] = {}
    for message in messages:
        for item in message.content:
            if isinstance(item, ToolCall):
                started[item.id] = item.name
            elif isinstance(item, ToolResultContent):
                started.pop(item.tool_call_id, None)
    records = []
    for tool_call_id, name in started.items():
        try:
            idempotent = registry.get(name).spec.capabilities.idempotent
        except (ToolNotFound, AttributeError):
            # An unknown tool cannot be proven safe to replay.
            idempotent = False
        records.append(ToolExecutionRecord(tool_call_id, "started", idempotent))
    return tuple(records)
