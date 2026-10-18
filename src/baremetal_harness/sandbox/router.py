from baremetal_harness.sandbox.base import SandboxExecutor
from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.tools.types import ToolCapabilities


class SandboxCapabilityUnavailable(RuntimeError):
    pass


class SandboxRouter:
    def __init__(
        self,
        *,
        process: SandboxExecutor | None = None,
        strong=None,
    ) -> None:
        self.process = process or ProcessSandbox()
        self.strong = strong

    async def select(
        self,
        capabilities: ToolCapabilities,
        require_strong: bool,
    ) -> SandboxExecutor:
        if not require_strong:
            return self.process
        if self.strong is None:
            raise SandboxCapabilityUnavailable(
                "strong sandbox backend is not configured"
            )
        report = await self.strong.capabilities()
        if not report.available:
            raise SandboxCapabilityUnavailable(report.reason)
        return self.strong
