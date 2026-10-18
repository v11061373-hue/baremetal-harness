from pathlib import Path

import pytest

from baremetal_harness.permissions.approval import InMemoryApprovalProvider
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.workspace.paths import WorkspaceEscape
from baremetal_harness.workspace.session import ArtifactApplied, WorkspaceSession


def test_artifact_application_is_explicit_and_atomic(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("original")
    session = WorkspaceSession.create(tmp_path / "sandboxes", source)
    (session.workspace / "notes.txt").write_text("approved")
    destination = tmp_path / "destination"
    destination.mkdir()

    applied = session.apply_artifacts(destination, (Path("notes.txt"),))

    assert applied == (Path("notes.txt"),)
    assert (destination / "notes.txt").read_text() == "approved"
    with pytest.raises(WorkspaceEscape):
        session.apply_artifacts(destination, (Path("../escape"),))


async def test_artifact_application_requires_bound_approval_and_emits_event(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    session = WorkspaceSession.create(tmp_path / "sandboxes", source)
    (session.workspace / "notes.txt").write_text("approved")
    destination = tmp_path / "destination"
    destination.mkdir()
    events = JsonlEventStore(tmp_path / "events.jsonl")

    applied = await session.apply_artifacts_approved(
        destination,
        (Path("notes.txt"),),
        approval_provider=InMemoryApprovalProvider({"apply-1": True}),
        event_store=events,
        request_id="apply-1",
    )

    assert applied == (Path("notes.txt"),)
    recorded = await events.load()
    assert isinstance(recorded[0].payload, ArtifactApplied)
    assert recorded[0].payload.paths == ("notes.txt",)


async def test_denied_artifact_application_does_not_modify_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    session = WorkspaceSession.create(tmp_path / "sandboxes", source)
    (session.workspace / "notes.txt").write_text("not approved")
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(PermissionError, match="denied"):
        await session.apply_artifacts_approved(
            destination,
            (Path("notes.txt"),),
            approval_provider=InMemoryApprovalProvider({}),
            event_store=JsonlEventStore(tmp_path / "events.jsonl"),
            request_id="apply-denied",
        )

    assert not (destination / "notes.txt").exists()
