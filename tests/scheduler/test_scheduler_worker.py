import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from baremetal_harness.app import create_app
from baremetal_harness.config import BareMetalHarnessConfig
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.permissions.approval import UnattendedApprovalProvider
from baremetal_harness.permissions.types import PermissionRequest
from baremetal_harness.scheduler.types import ScheduledTask, ScheduledTaskStatus
from baremetal_harness.tools.types import RiskLevel, ToolCapabilities


async def _app(tmp_path: Path, provider) -> object:
    workspace = tmp_path / "project"
    workspace.mkdir()
    return await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=provider,
    )


async def _wait_for(predicate, *, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.01)
    return False


async def test_due_task_is_executed_by_the_running_worker(tmp_path: Path) -> None:
    app = await _app(
        tmp_path,
        ScriptedModel(((TextDelta("reviewed the notes"), ResponseCompleted("stop")),)),
    )
    await app.scheduler.add(
        ScheduledTask.once(
            "job-1",
            "review notes",
            datetime.now(UTC) - timedelta(seconds=1),
        )
    )

    await app.start_scheduler(poll_interval=0.01)
    try:
        fired = await _wait_for(
            lambda: _status(app, "job-1", ScheduledTaskStatus.DONE)
        )
    finally:
        await app.aclose()

    assert fired
    task = await app.scheduler.get("job-1")
    assert task.child_run_id


async def test_future_task_is_not_executed_early(tmp_path: Path) -> None:
    app = await _app(tmp_path, FakeModel([]))
    await app.scheduler.add(
        ScheduledTask.once(
            "job-later",
            "not yet",
            datetime.now(UTC) + timedelta(hours=1),
        )
    )

    await app.start_scheduler(poll_interval=0.01)
    try:
        await asyncio.sleep(0.1)
    finally:
        await app.aclose()

    task = await app.scheduler.get("job-later")
    assert task.status is ScheduledTaskStatus.SCHEDULED
    assert task.attempts == 0


async def test_failing_scheduled_run_is_recorded_as_failed(tmp_path: Path) -> None:
    # A model that never emits a stop finish reason leaves the run unfinished.
    app = await _app(
        tmp_path,
        ScriptedModel(((TextDelta("partial"), ResponseCompleted("length")),)),
    )
    await app.scheduler.add(
        ScheduledTask.once(
            "job-fail",
            "will not finish",
            datetime.now(UTC) - timedelta(seconds=1),
            idempotent=False,
        )
    )

    await app.start_scheduler(poll_interval=0.01)
    try:
        failed = await _wait_for(
            lambda: _status(app, "job-fail", ScheduledTaskStatus.FAILED)
        )
    finally:
        await app.aclose()

    assert failed
    assert "failed" in (await app.scheduler.get("job-fail")).last_error


async def test_stopping_the_app_stops_the_worker(tmp_path: Path) -> None:
    app = await _app(tmp_path, FakeModel([]))

    await app.start_scheduler(poll_interval=0.01)
    assert app.scheduler_worker is not None
    await app.aclose()

    assert app.scheduler_worker is None


async def test_starting_twice_does_not_spawn_a_second_worker(
    tmp_path: Path,
) -> None:
    app = await _app(tmp_path, FakeModel([]))

    await app.start_scheduler(poll_interval=0.01)
    first = app.scheduler_worker
    await app.start_scheduler(poll_interval=0.01)
    try:
        assert app.scheduler_worker is first
    finally:
        await app.aclose()


async def test_task_left_running_by_a_crash_is_requeued_at_startup(
    tmp_path: Path,
) -> None:
    app = await _app(tmp_path, FakeModel([]))
    await app.scheduler.add(
        ScheduledTask.once(
            "job-orphan",
            "interrupted",
            datetime.now(UTC) + timedelta(hours=1),
        )
    )
    # Simulate a process that died while the task was in flight.
    await app.scheduler.claim_due(datetime.now(UTC) + timedelta(days=1), 1)
    assert (
        await app.scheduler.get("job-orphan")
    ).status is ScheduledTaskStatus.RUNNING

    await app.start_scheduler(poll_interval=0.01)
    try:
        assert (
            await app.scheduler.get("job-orphan")
        ).status is ScheduledTaskStatus.SCHEDULED
    finally:
        await app.aclose()


async def test_unattended_runs_deny_instead_of_prompting() -> None:
    request = PermissionRequest(
        "req-1",
        "run-1",
        "call-1",
        "run_command",
        "<redacted>",
        ToolCapabilities(subprocess=True, risk_level=RiskLevel.HIGH),
        "high risk",
    )

    resolution = await UnattendedApprovalProvider().resolve(request)

    assert resolution.approved is False
    assert "unattended" in resolution.reason


async def test_scheduled_run_cannot_escalate_via_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=ScriptedModel(
            (
                (
                    ToolCallDelta(
                        0, "call-1", "run_command", '{"argv":["echo","hi"]}'
                    ),
                    ResponseCompleted("tool_calls"),
                ),
                (TextDelta("done"), ResponseCompleted("stop")),
            )
        ),
    )
    # run_command is HIGH risk and non-idempotent, so the policy asks. With no
    # human attached the ask must resolve to a denial, not a prompt.
    result = await app.scheduler_runtime.runner.agent.run("run a command")
    await app.aclose()

    outputs = [
        item.output
        for message in result.messages
        for item in message.content
        if hasattr(item, "output")
    ]
    assert outputs == ["permission denied"]


async def _status(app, task_id: str, expected: ScheduledTaskStatus) -> bool:
    return (await app.scheduler.get(task_id)).status is expected


async def test_background_runs_cannot_delegate_to_reach_a_human(
    tmp_path: Path,
) -> None:
    app = await _app(tmp_path, FakeModel([]))
    try:
        interactive = {tool.spec.name for tool in app.agent.tools.values()}
        unattended = {
            tool.spec.name
            for tool in app.scheduler_runtime.runner.agent.tools.values()
        }
    finally:
        await app.aclose()

    # Children are built by a factory holding the interactive approval
    # provider, so an unattended run must not be able to spawn one.
    assert "delegate_task" in interactive
    assert "delegate_task" not in unattended
    assert interactive - unattended == {"delegate_task"}
