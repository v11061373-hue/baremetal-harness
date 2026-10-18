import asyncio
import os
import signal
import sys

from baremetal_harness.sandbox.capabilities import SandboxCapabilities, SandboxStrength
from baremetal_harness.sandbox.types import (
    Command,
    SandboxCapabilityError,
    SandboxPolicy,
    SandboxResourceExceeded,
    SandboxResult,
    SandboxTimeout,
)
from baremetal_harness.workspace.diff import changed_paths, snapshot_files
from baremetal_harness.workspace.paths import WorkspaceEscape, resolve_workspace_path


class ProcessSandbox:
    async def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            True,
            SandboxStrength.PROCESS,
            False,
            False,
            True,
            "process backend is available but does not enforce strong isolation",
        )

    async def execute(
        self,
        command: Command,
        policy: SandboxPolicy,
    ) -> SandboxResult:
        if sys.platform == "win32":
            raise SandboxCapabilityError(
                "process group cleanup is unsupported on Windows"
            )
        if policy.network != "deny":
            raise SandboxCapabilityError(
                "process backend only accepts deny network policy"
            )
        workspace = policy.workspace.resolve()
        try:
            cwd = resolve_workspace_path(
                workspace,
                command.cwd.resolve().relative_to(workspace),
            )
        except (ValueError, WorkspaceEscape) as exc:
            raise SandboxCapabilityError(
                "command cwd is outside the workspace"
            ) from exc
        if not command.argv:
            raise SandboxCapabilityError("command argv must not be empty")

        allowed = set(policy.allowed_environment)
        environment = {
            name: value
            for name, value in os.environ.items()
            if name in allowed
        }
        environment.update(
            {
                name: value
                for name, value in command.environment.items()
                if name in allowed
            }
        )
        before = snapshot_files(workspace)
        process = await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=cwd,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=policy.timeout_seconds,
            )
        except TimeoutError as exc:
            await self._terminate(process)
            raise SandboxTimeout("process exceeded time limit") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise

        if len(stdout_bytes) + len(stderr_bytes) > policy.max_output_bytes:
            raise SandboxResourceExceeded("process output exceeded limit")
        after = snapshot_files(workspace)
        return SandboxResult(
            process.returncode,
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
            changed_paths(before, after),
            ("network isolation is not enforced by process backend",),
        )

    async def _terminate(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
