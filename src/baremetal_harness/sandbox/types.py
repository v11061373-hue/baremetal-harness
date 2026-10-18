from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class SandboxError(RuntimeError):
    pass


class SandboxCapabilityError(SandboxError):
    pass


class SandboxTimeout(SandboxError):
    pass


class SandboxResourceExceeded(SandboxError):
    pass


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    workspace: Path
    filesystem: str
    network: str
    allowed_environment: tuple[str, ...]
    timeout_seconds: float
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class Command:
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    changed_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()
