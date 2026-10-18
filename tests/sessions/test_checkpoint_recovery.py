from baremetal_harness.sessions.recovery import (
    RecoveryDecision,
    ToolExecutionRecord,
    decide_recovery,
)


def test_completed_tool_is_not_repeated() -> None:
    decision = decide_recovery(
        checkpoint_valid=True,
        executions=(
            ToolExecutionRecord("call-1", "completed", True),
        ),
    )

    assert decision is RecoveryDecision.RESUME


def test_pending_non_idempotent_tool_requires_approval() -> None:
    decision = decide_recovery(
        checkpoint_valid=True,
        executions=(
            ToolExecutionRecord("call-1", "started", False),
        ),
    )

    assert decision is RecoveryDecision.REQUIRES_APPROVAL


def test_corrupt_checkpoint_is_unrecoverable() -> None:
    assert (
        decide_recovery(checkpoint_valid=False, executions=())
        is RecoveryDecision.UNRECOVERABLE
    )
