from typing import Protocol

from baremetal_harness.sandbox.types import Command, SandboxPolicy, SandboxResult


class SandboxExecutor(Protocol):
    async def execute(
        self,
        command: Command,
        policy: SandboxPolicy,
    ) -> SandboxResult: ...
