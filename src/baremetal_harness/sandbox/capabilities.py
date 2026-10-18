from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class SandboxStrength(StrEnum):
    PROCESS = "process"
    STRONG = "strong"


@dataclass(frozen=True, slots=True)
class SandboxCapabilities:
    available: bool
    strength: SandboxStrength
    network_isolation: bool
    read_only_root: bool
    resource_limits: bool
    reason: str


class SandboxCapabilityProvider(Protocol):
    async def capabilities(self) -> SandboxCapabilities: ...
