from dataclasses import dataclass
from enum import StrEnum

from baremetal_harness.tools.types import ToolCapabilities


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True, slots=True)
class PermissionEvaluation:
    decision: PermissionDecision
    reason: str


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    request_id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    arguments_preview: str
    capabilities: ToolCapabilities
    reason: str


@dataclass(frozen=True, slots=True)
class ApprovalResolution:
    request_id: str
    approved: bool
    reason: str
