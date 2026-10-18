from pathlib import Path

import pytest

from baremetal_harness.workspace.paths import WorkspaceEscape, resolve_workspace_path
from baremetal_harness.workspace.session import WorkspaceSession


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceEscape):
        resolve_workspace_path(tmp_path, "../secret")


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceEscape):
        resolve_workspace_path(tmp_path, tmp_path.parent / "secret")


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    (tmp_path / "link").symlink_to(outside)

    with pytest.raises(WorkspaceEscape):
        resolve_workspace_path(tmp_path, "link")


def test_workspace_session_copies_without_mutating_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("original")

    session = WorkspaceSession.create(tmp_path / "sandboxes", source)
    (session.workspace / "README.md").write_text("changed")

    assert (source / "README.md").read_text() == "original"
    assert session.manifest() == (Path("README.md"),)
