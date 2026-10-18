from pathlib import Path


class WorkspaceEscape(ValueError):
    pass


def resolve_workspace_path(root: Path, relative: str | Path) -> Path:
    workspace = root.resolve()
    requested = Path(relative)
    if requested.is_absolute():
        raise WorkspaceEscape("absolute paths are outside the workspace")
    candidate = (workspace / requested).resolve()
    if not candidate.is_relative_to(workspace):
        raise WorkspaceEscape("path escapes the workspace")
    return candidate
