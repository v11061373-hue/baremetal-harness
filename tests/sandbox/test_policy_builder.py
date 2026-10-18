from pathlib import Path

import pytest

from baremetal_harness.sandbox.policy import (
    PermissionDenied,
    SandboxLimits,
    SandboxPolicyBuilder,
)
from baremetal_harness.tools.types import ToolCapabilities


def test_builder_caps_limits_and_environment(tmp_path: Path) -> None:
    policy = SandboxPolicyBuilder(SandboxLimits(10.0, 1000)).build(
        ToolCapabilities(filesystem="read", secrets=("PATH",)),
        tmp_path,
        requested_timeout=99.0,
        requested_environment=("PATH",),
    )
    assert policy.filesystem == "read"
    assert policy.network == "deny"
    assert policy.timeout_seconds == 10.0
    assert policy.max_output_bytes == 1000
    assert policy.allowed_environment == ("PATH",)


def test_builder_rejects_undeclared_environment(tmp_path: Path) -> None:
    with pytest.raises(PermissionDenied):
        SandboxPolicyBuilder().build(
            ToolCapabilities(),
            tmp_path,
            requested_timeout=1.0,
            requested_environment=("SECRET",),
        )
