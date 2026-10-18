from dataclasses import dataclass
from pathlib import Path

from baremetal_harness.sandbox.types import SandboxPolicy
from baremetal_harness.tools.types import ToolCapabilities


class PermissionDenied(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    max_timeout_seconds: float = 300.0
    max_output_bytes: int = 1_000_000


class SandboxPolicyBuilder:
    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    def build(
        self,
        capabilities: ToolCapabilities,
        workspace: Path,
        requested_timeout: float,
        requested_environment: tuple[str, ...],
    ) -> SandboxPolicy:
        undeclared = set(requested_environment) - set(capabilities.secrets)
        if undeclared:
            raise PermissionDenied("requested environment is not declared")
        if capabilities.filesystem not in {"none", "read", "workspace-write"}:
            raise PermissionDenied("unsupported filesystem capability")
        return SandboxPolicy(
            workspace.resolve(),
            capabilities.filesystem,
            "deny",
            tuple(
                name
                for name in requested_environment
                if name in capabilities.secrets
            ),
            min(max(requested_timeout, 0.0), self.limits.max_timeout_seconds),
            self.limits.max_output_bytes,
        )
