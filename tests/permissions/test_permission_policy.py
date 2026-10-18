from baremetal_harness.permissions.policy import DefaultPermissionPolicy
from baremetal_harness.permissions.types import PermissionDecision
from baremetal_harness.tools.types import RiskLevel, ToolCapabilities


def test_low_risk_read_is_allowed() -> None:
    result = DefaultPermissionPolicy().evaluate(
        tool_name="read_file",
        capabilities=ToolCapabilities(filesystem="read"),
        arguments={"path": "README.md"},
    )
    assert result.decision is PermissionDecision.ALLOW
    assert result.reason == "read-only tool"


def test_high_risk_subprocess_requires_approval() -> None:
    result = DefaultPermissionPolicy().evaluate(
        tool_name="run_command",
        capabilities=ToolCapabilities(
            filesystem="workspace-write",
            subprocess=True,
            risk_level=RiskLevel.HIGH,
            side_effects=True,
            idempotent=False,
        ),
        arguments={"argv": ["python", "-V"]},
    )
    assert result.decision is PermissionDecision.ASK
    assert result.reason == "non-idempotent subprocess or workspace write"


def test_undeclared_secret_is_denied() -> None:
    result = DefaultPermissionPolicy().evaluate(
        tool_name="unsafe",
        capabilities=ToolCapabilities(),
        arguments={"api_key": "hidden"},
    )
    assert result.decision is PermissionDecision.DENY
