import sys
from pathlib import Path

import pytest

from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.sandbox.types import (
    Command,
    SandboxPolicy,
    SandboxResourceExceeded,
    SandboxTimeout,
)


async def test_timeout_terminates_process(tmp_path: Path) -> None:
    sandbox = ProcessSandbox()
    policy = SandboxPolicy(tmp_path, "workspace-write", "deny", (), 0.05, 4096)
    command = Command(
        (sys.executable, "-c", "import time; time.sleep(10)"),
        tmp_path,
        {},
    )

    with pytest.raises(SandboxTimeout):
        await sandbox.execute(command, policy)


async def test_environment_is_allowlisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "must-not-leak")
    sandbox = ProcessSandbox()
    policy = SandboxPolicy(
        tmp_path,
        "workspace-write",
        "deny",
        ("PATH",),
        2.0,
        4096,
    )
    command = Command(
        (
            sys.executable,
            "-c",
            "import os; print(os.environ.get('SECRET_TOKEN', 'missing'))",
        ),
        tmp_path,
        {},
    )

    result = await sandbox.execute(command, policy)

    assert result.stdout.strip() == "missing"
    assert result.warnings == (
        "network isolation is not enforced by process backend",
    )


async def test_output_over_limit_is_rejected(tmp_path: Path) -> None:
    sandbox = ProcessSandbox()
    policy = SandboxPolicy(tmp_path, "workspace-write", "deny", (), 2.0, 32)
    command = Command(
        (sys.executable, "-c", "print('x' * 1024)"),
        tmp_path,
        {},
    )

    with pytest.raises(SandboxResourceExceeded):
        await sandbox.execute(command, policy)


async def test_changed_paths_are_relative_to_workspace(tmp_path: Path) -> None:
    sandbox = ProcessSandbox()
    policy = SandboxPolicy(tmp_path, "workspace-write", "deny", (), 2.0, 4096)
    command = Command(
        (
            sys.executable,
            "-c",
            "from pathlib import Path; Path('created.txt').write_text('ok')",
        ),
        tmp_path,
        {},
    )

    result = await sandbox.execute(command, policy)

    assert result.exit_code == 0
    assert result.changed_paths == (Path("created.txt"),)
