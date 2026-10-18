import hashlib
from pathlib import Path


def snapshot_files(root: Path) -> dict[Path, str]:
    snapshot: dict[Path, str] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[path.relative_to(root)] = digest
    return snapshot


def changed_paths(
    before: dict[Path, str],
    after: dict[Path, str],
) -> tuple[Path, ...]:
    paths = set(before) | set(after)
    return tuple(sorted(path for path in paths if before.get(path) != after.get(path)))
