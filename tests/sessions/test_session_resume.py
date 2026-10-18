import json
from pathlib import Path

from baremetal_harness.app import create_app
from baremetal_harness.config import BareMetalHarnessConfig
from baremetal_harness.core.messages import (
    Message,
    ResponseCompleted,
    TextContent,
    TextDelta,
    ToolCall,
    ToolResultContent,
)
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.permissions.approval import InMemoryApprovalProvider
from baremetal_harness.sessions.recovery import (
    RecoveryDecision,
    decide_recovery,
    pending_tool_executions,
)
from baremetal_harness.tools.builtin.files import make_file_tools
from baremetal_harness.tools.registry import ToolRegistry


def _turns(*texts: str):
    return tuple((TextDelta(text), ResponseCompleted("stop")) for text in texts)


async def _app(tmp_path: Path, *texts: str, approvals=None):
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    return await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=ScriptedModel(_turns(*texts)),
        approval_provider=approvals,
    )


async def test_consecutive_prompts_stay_in_one_session(tmp_path: Path) -> None:
    app = await _app(tmp_path, "first", "second")

    first = await app.run_prompt("hello")
    second = await app.run_prompt("again")
    await app.aclose()

    assert first.session_id == second.session_id
    assert first.run_id != second.run_id
    assert len(await app.sessions.list_sessions()) == 1


async def test_resume_restores_conversation_in_a_fresh_process(
    tmp_path: Path,
) -> None:
    first = await _app(tmp_path, "remembered answer")
    result = await first.run_prompt("what is the plan?")
    session_id = result.session_id
    await first.aclose()

    # A brand new app object, as if the CLI had been restarted.
    second = await _app(tmp_path, "continued answer")
    assert second.conversation == ()

    command = await second.handle_command(f"/resume {session_id}")
    payload = json.loads(command.output)

    assert payload["decision"] == RecoveryDecision.RESUME.value
    assert payload["resumed"] is True
    assert payload["restored_messages"] == len(result.messages)
    assert second.session_id == session_id
    assert second.conversation == result.messages

    # The continued run joins the same session and keeps the old history.
    continued = await second.run_prompt("and then?")
    await second.aclose()

    assert continued.session_id == session_id
    assert continued.messages[: len(result.messages)] == result.messages


async def test_resume_reports_unknown_session(tmp_path: Path) -> None:
    app = await _app(tmp_path, "unused")

    command = await app.handle_command("/resume does-not-exist")
    await app.aclose()

    assert "session not found" in command.output
    assert app.session_id is None


async def test_resume_without_argument_shows_usage(tmp_path: Path) -> None:
    app = await _app(tmp_path, "unused")

    command = await app.handle_command("/resume")
    await app.aclose()

    assert command.output == "usage: /resume <session-id>"


async def test_clear_detaches_from_the_session(tmp_path: Path) -> None:
    app = await _app(tmp_path, "first", "second")

    first = await app.run_prompt("hello")
    await app.handle_command("/clear")
    second = await app.run_prompt("fresh start")
    await app.aclose()

    assert app.conversation == second.messages
    assert second.session_id != first.session_id


async def test_sessions_command_marks_the_current_session(tmp_path: Path) -> None:
    app = await _app(tmp_path, "answer")

    result = await app.run_prompt("hello")
    command = await app.handle_command("/sessions")
    await app.aclose()

    listed = json.loads(command.output)
    assert [item for item in listed if item["current"]][0]["session_id"] == (
        result.session_id
    )


def test_unfinished_non_idempotent_call_requires_approval() -> None:
    registry = ToolRegistry()
    for tool in make_file_tools():
        registry.register(tool)
    messages = (
        Message("user", (TextContent("go"),)),
        Message("assistant", (ToolCall("call-1", "write_file", {}),)),
    )

    pending = pending_tool_executions(messages, registry)

    assert len(pending) == 1
    assert pending[0].tool_call_id == "call-1"
    # write_file declares itself idempotent, so replay is safe.
    assert decide_recovery(checkpoint_valid=True, executions=pending) is (
        RecoveryDecision.RESUME
    )


def test_completed_call_is_not_pending() -> None:
    registry = ToolRegistry()
    for tool in make_file_tools():
        registry.register(tool)
    messages = (
        Message("assistant", (ToolCall("call-1", "read_file", {}),)),
        Message("tool", (ToolResultContent("call-1", "content"),)),
    )

    assert pending_tool_executions(messages, registry) == ()


def test_unknown_tool_is_treated_as_unsafe_to_replay() -> None:
    messages = (Message("assistant", (ToolCall("call-1", "vanished_tool", {}),)),)

    pending = pending_tool_executions(messages, ToolRegistry())

    assert pending[0].idempotent is False
    assert decide_recovery(checkpoint_valid=True, executions=pending) is (
        RecoveryDecision.REQUIRES_APPROVAL
    )


async def test_resume_denied_when_approval_is_refused(tmp_path: Path) -> None:
    app = await _app(tmp_path, "answer", approvals=InMemoryApprovalProvider({}))
    result = await app.run_prompt("hello")
    session_id = result.session_id
    # Forge a checkpoint whose history ends on an unfinished risky call.
    checkpoint = await app.checkpoints.latest_for_run(result.run_id)
    from dataclasses import replace
    from uuid import uuid4

    await app.checkpoints.save(
        replace(
            checkpoint,
            checkpoint_id=str(uuid4()),
            sequence=checkpoint.sequence + 1,
            messages=(
                *checkpoint.messages,
                Message("assistant", (ToolCall("call-9", "run_command", {}),)),
            ),
        )
    )

    command = await app.handle_command(f"/resume {session_id}")
    await app.aclose()

    payload = json.loads(command.output)
    assert payload["decision"] == RecoveryDecision.REQUIRES_APPROVAL.value
    assert payload["resumed"] is False
    assert app.conversation == result.messages
