import pytest

from baremetal_harness.agent.state import RunStatus, transition
from baremetal_harness.core.errors import InvariantViolation


def test_model_call_can_complete_or_validate_tools() -> None:
    assert transition(RunStatus.CALLING_MODEL, RunStatus.COMPLETED) is RunStatus.COMPLETED
    assert (
        transition(RunStatus.CALLING_MODEL, RunStatus.VALIDATING_TOOLS)
        is RunStatus.VALIDATING_TOOLS
    )


def test_illegal_transition_fails_closed() -> None:
    with pytest.raises(InvariantViolation):
        transition(RunStatus.CREATED, RunStatus.EXECUTING_TOOLS)
