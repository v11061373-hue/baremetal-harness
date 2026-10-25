from baremetal_harness.agent.loop import ApprovalRequested, RunResult
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import Message, ToolCall, ToolResultContent
from baremetal_harness.evals.assertions import evaluate_assertion
from baremetal_harness.evals.types import EvalAssertion


def _result_with_tool_call(name: str) -> RunResult:
    return RunResult(
        "r",
        "s",
        RunStatus.COMPLETED,
        "",
        (
            Message("assistant", (ToolCall("c1", name, {}),)),
            Message("tool", (ToolResultContent("c1", "done"),)),
        ),
        (),
    )


def _result_with_approvals(count: int) -> RunResult:
    events = tuple(
        EventEnvelope.create(
            run_id="r",
            session_id="s",
            sequence=i + 1,
            payload=ApprovalRequested(
                f"req-{i}", "call-1", "write_file", "needs approval"
            ),
        )
        for i in range(count)
    )
    return RunResult("r", "s", RunStatus.COMPLETED, "", (), events)


def test_tool_called_passes() -> None:
    assert (
        evaluate_assertion(
            EvalAssertion("tool_called", "read_file"),
            _result_with_tool_call("read_file"),
        )
        is None
    )


def test_tool_called_fails() -> None:
    assert (
        evaluate_assertion(
            EvalAssertion("tool_called", "write_file"),
            _result_with_tool_call("read_file"),
        )
        is not None
    )


def test_tool_not_called_passes() -> None:
    assert (
        evaluate_assertion(
            EvalAssertion("tool_not_called", "write_file"),
            _result_with_tool_call("read_file"),
        )
        is None
    )


def test_tool_not_called_fails() -> None:
    assert (
        evaluate_assertion(
            EvalAssertion("tool_not_called", "read_file"),
            _result_with_tool_call("read_file"),
        )
        is not None
    )


def test_approval_count_passes() -> None:
    assert (
        evaluate_assertion(
            EvalAssertion("approval_count", 2), _result_with_approvals(2)
        )
        is None
    )


def test_approval_count_fails() -> None:
    assert (
        evaluate_assertion(
            EvalAssertion("approval_count", 1), _result_with_approvals(2)
        )
        is not None
    )


def test_no_secret_in_trace_passes() -> None:
    result = RunResult("r", "s", RunStatus.COMPLETED, "done", (), ())
    assert (
        evaluate_assertion(EvalAssertion("no_secret_in_trace", "sk-123"), result)
        is None
    )


def test_no_secret_in_trace_fails_on_output() -> None:
    result = RunResult(
        "r", "s", RunStatus.COMPLETED, "key sk-123 leaked", (), ()
    )
    assert (
        evaluate_assertion(EvalAssertion("no_secret_in_trace", "sk-123"), result)
        is not None
    )


def test_no_secret_in_trace_fails_on_tool_result() -> None:
    result = RunResult(
        "r",
        "s",
        RunStatus.COMPLETED,
        "",
        (Message("tool", (ToolResultContent("c1", "secret sk-123 here"),)),),
        (),
    )
    assert (
        evaluate_assertion(EvalAssertion("no_secret_in_trace", "sk-123"), result)
        is not None
    )
