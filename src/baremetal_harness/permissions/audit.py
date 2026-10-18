import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from baremetal_harness.permissions.types import PermissionDecision


@dataclass(frozen=True, slots=True)
class PermissionAudit:
    tool_name: str
    decision: PermissionDecision
    capability_summary: str
    argument_digest: str
    request_id: str | None
    resolution_id: str | None
    timestamp: datetime


def digest_arguments(arguments: dict[str, object]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, default=type).encode()
    return hashlib.sha256(encoded).hexdigest()
