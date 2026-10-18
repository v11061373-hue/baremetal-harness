import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.permissions.types import PermissionRequest
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.tools.types import RiskLevel, ToolCapabilities
from baremetal_harness.workspace.diff import snapshot_files
from baremetal_harness.workspace.paths import WorkspaceEscape, resolve_workspace_path


class ApprovalProvider(Protocol):
    async def resolve(self, request: PermissionRequest): ...


@dataclass(frozen=True, slots=True)
class ArtifactApplied:
    destination: str
    paths: tuple[str, ...]


@dataclass(slots=True)
class WorkspaceSession:
    sandbox_id: str
    root: Path
    workspace: Path
    artifacts: Path

    @classmethod
    def create(
        cls,
        root: Path,
        source: Path | None = None,
    ) -> "WorkspaceSession":
        sandbox_id = str(uuid4())
        session_root = root.resolve() / sandbox_id
        workspace = session_root / "workspace"
        artifacts = session_root / "artifacts"
        session_root.mkdir(parents=True)
        artifacts.mkdir()
        if source is None:
            workspace.mkdir()
        else:
            source_root = source.resolve()

            def reject_symlinks(
                current: str,
                names: list[str],
            ) -> set[str]:
                current_path = Path(current)
                return {
                    name
                    for name in names
                    if (current_path / name).is_symlink()
                }

            shutil.copytree(
                source_root,
                workspace,
                symlinks=False,
                ignore=reject_symlinks,
            )
        return cls(sandbox_id, session_root, workspace, artifacts)

    def manifest(self) -> tuple[Path, ...]:
        return tuple(snapshot_files(self.workspace))

    def apply_artifacts(
        self,
        destination: Path,
        approved_paths: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        manifest = set(self.manifest())
        applied = []
        for relative in approved_paths:
            if relative not in manifest:
                raise WorkspaceEscape("artifact is not in the workspace manifest")
            source = resolve_workspace_path(self.workspace, relative)
            target = resolve_workspace_path(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.baremetal_harness.",
                suffix=".tmp",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with source.open("rb") as reader, os.fdopen(
                    descriptor, "wb"
                ) as writer:
                    shutil.copyfileobj(reader, writer)
                    writer.flush()
                    os.fsync(writer.fileno())
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            applied.append(relative)
        return tuple(applied)

    async def apply_artifacts_approved(
        self,
        destination: Path,
        approved_paths: tuple[Path, ...],
        *,
        approval_provider: ApprovalProvider,
        event_store: JsonlEventStore,
        request_id: str | None = None,
    ) -> tuple[Path, ...]:
        manifest = set(self.manifest())
        normalized = tuple(Path(path) for path in approved_paths)
        for relative in normalized:
            if relative not in manifest:
                raise WorkspaceEscape("artifact is not in the workspace manifest")
            resolve_workspace_path(self.workspace, relative)
            resolve_workspace_path(destination, relative)
        path_values = tuple(path.as_posix() for path in normalized)
        operation_id = request_id or str(uuid4())
        resolution = await approval_provider.resolve(
            PermissionRequest(
                operation_id,
                f"artifact-{self.sandbox_id}",
                operation_id,
                "apply_artifacts",
                json.dumps(
                    {"paths": path_values},
                    separators=(",", ":"),
                ),
                ToolCapabilities(
                    filesystem="workspace-write",
                    risk_level=RiskLevel.HIGH,
                    side_effects=True,
                    idempotent=False,
                ),
                "apply sandbox artifacts to the destination workspace",
            )
        )
        if not resolution.approved:
            raise PermissionError(f"artifact application denied: {resolution.reason}")
        applied = self.apply_artifacts(destination, normalized)
        previous = await event_store.load()
        run_id = f"artifact-{self.sandbox_id}"
        run_events = tuple(event for event in previous if event.run_id == run_id)
        envelope = EventEnvelope.create(
            run_id=run_id,
            session_id=self.sandbox_id,
            sequence=len(run_events) + 1,
            payload=ArtifactApplied(
                str(destination.resolve()),
                tuple(path.as_posix() for path in applied),
            ),
            parent_event_id=run_events[-1].event_id if run_events else None,
        )
        await event_store.append(envelope)
        return applied
