import asyncio
from pathlib import PurePosixPath

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


class DockerSandbox:
    def __init__(
        self,
        *,
        image: str = "python:3.12-slim",
        allowed_images: tuple[str, ...] = ("python:3.12-slim",),
    ) -> None:
        if image not in allowed_images:
            raise ValueError("docker image is not allowlisted")
        self.image = image

    async def capabilities(self) -> SandboxCapabilities:
        for argv, failure_reason in (
            (
                ("docker", "version", "--format", "{{.Server.Version}}"),
                "docker daemon is unavailable",
            ),
            (
                ("docker", "image", "inspect", self.image),
                "configured docker image is unavailable",
            ),
        ):
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.communicate(), timeout=3.0)
            except FileNotFoundError:
                return self._unavailable("docker CLI is unavailable")
            except TimeoutError:
                return self._unavailable("docker capability check timed out")
            if process.returncode != 0:
                return self._unavailable(failure_reason)
        return SandboxCapabilities(
            True,
            SandboxStrength.STRONG,
            True,
            True,
            True,
            "docker strong sandbox is available",
        )

    async def execute(
        self,
        command: Command,
        policy: SandboxPolicy,
    ) -> SandboxResult:
        report = await self.capabilities()
        if not report.available:
            raise SandboxCapabilityError(report.reason)
        if policy.network != "deny":
            raise SandboxCapabilityError(
                "docker backend only accepts deny network policy"
            )
        workspace = policy.workspace.resolve()
        cwd = command.cwd.resolve()
        if not cwd.is_relative_to(workspace):
            raise SandboxCapabilityError(
                "command cwd is outside the workspace"
            )
        relative = cwd.relative_to(workspace)
        container_cwd = str(PurePosixPath("/workspace") / PurePosixPath(relative))
        mount_mode = "readonly" if policy.filesystem == "read" else "rw"
        mount = (
            f"type=bind,src={workspace},dst=/workspace,{mount_mode}"
        )
        argv = (
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--pids-limit",
            "64",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--mount",
            mount,
            "--workdir",
            container_cwd,
            self.image,
            *command.argv,
        )
        before = snapshot_files(workspace)
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=policy.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise SandboxTimeout("docker process exceeded time limit") from exc
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if len(stdout) + len(stderr) > policy.max_output_bytes:
            raise SandboxResourceExceeded("docker output exceeded limit")
        after = snapshot_files(workspace)
        return SandboxResult(
            process.returncode,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            changed_paths(before, after),
        )

    @staticmethod
    def _unavailable(reason: str) -> SandboxCapabilities:
        return SandboxCapabilities(
            False,
            SandboxStrength.STRONG,
            False,
            False,
            False,
            reason,
        )
