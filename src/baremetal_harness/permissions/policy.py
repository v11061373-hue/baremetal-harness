from collections.abc import Mapping

from baremetal_harness.permissions.types import PermissionDecision, PermissionEvaluation
from baremetal_harness.tools.types import RiskLevel, ToolCapabilities


class DefaultPermissionPolicy:
    def evaluate(
        self,
        *,
        tool_name: str,
        capabilities: ToolCapabilities,
        arguments: Mapping[str, object],
    ) -> PermissionEvaluation:
        secret_keys = {"api_key", "token", "secret", "password"}
        if (
            any(key.casefold() in secret_keys for key in arguments)
            and not capabilities.secrets
        ):
            return PermissionEvaluation(
                PermissionDecision.DENY, "undeclared secret request"
            )
        if capabilities.network == "unrestricted":
            return PermissionEvaluation(PermissionDecision.ASK, "unrestricted network")
        if capabilities.risk_level is RiskLevel.CRITICAL:
            return PermissionEvaluation(PermissionDecision.ASK, "critical risk tool")
        if (
            not capabilities.idempotent
            and (
                capabilities.subprocess
                or capabilities.filesystem == "workspace-write"
            )
        ):
            return PermissionEvaluation(
                PermissionDecision.ASK,
                "non-idempotent subprocess or workspace write",
            )
        valid_filesystems = {"none", "read", "workspace-write"}
        valid_networks = {"deny", "unrestricted"}
        if (
            capabilities.filesystem not in valid_filesystems
            or capabilities.network not in valid_networks
        ):
            return PermissionEvaluation(
                PermissionDecision.DENY, "unknown capability value"
            )
        if (
            capabilities.filesystem == "read"
            and not capabilities.subprocess
            and capabilities.network == "deny"
            and not capabilities.secrets
        ):
            return PermissionEvaluation(PermissionDecision.ALLOW, "read-only tool")
        if (
            capabilities.filesystem == "none"
            and not capabilities.subprocess
            and capabilities.network == "deny"
            and not capabilities.secrets
        ):
            return PermissionEvaluation(PermissionDecision.ALLOW, "pure computation")
        # A tool that declares no side effects, no network and no writes is safe
        # to run unattended even when it shells out, because the capability
        # declaration - not the presence of a subprocess - is the contract.
        if (
            capabilities.filesystem in {"none", "read"}
            and capabilities.network == "deny"
            and not capabilities.secrets
            and not capabilities.side_effects
            and capabilities.idempotent
            and capabilities.risk_level is RiskLevel.LOW
        ):
            return PermissionEvaluation(
                PermissionDecision.ALLOW,
                "read-only inspection tool",
            )
        return PermissionEvaluation(PermissionDecision.ASK, "tool has side effects")
