from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class ToolCapabilities:
    filesystem: str = "none"
    network: str = "deny"
    subprocess: bool = False
    secrets: tuple[str, ...] = ()
    risk_level: RiskLevel = RiskLevel.LOW
    side_effects: bool = False
    idempotent: bool = True


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, object]
    capabilities: ToolCapabilities


@dataclass(frozen=True, slots=True)
class ToolContext:
    run_id: str
    session_id: str
    workspace: Path


ToolHandler = Callable[[Mapping[str, object], ToolContext], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler
