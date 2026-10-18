import sys
from pathlib import Path

from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.sandbox.types import Command, SandboxPolicy


async def assert_executor_contract(executor, tmp_path: Path) -> None:
    policy = SandboxPolicy(tmp_path, "workspace-write", "deny", ("PATH",), 2.0, 4096)
    result = await executor.execute(
        Command((sys.executable, "-c", "print('ok')"), tmp_path, {}),
        policy,
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.stderr == ""


async def test_process_sandbox_contract(tmp_path: Path) -> None:
    await assert_executor_contract(ProcessSandbox(), tmp_path)
