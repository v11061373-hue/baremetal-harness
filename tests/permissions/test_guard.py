from baremetal_harness.permissions.guard import DestructiveCommandGuard
from baremetal_harness.permissions.types import PermissionDecision


def test_destructive_command_denied() -> None:
    result = DestructiveCommandGuard().evaluate(
        tool_name="run_command",
        arguments={"argv": ["rm", "-rf", "/"]},
    )
    assert result is not None
    assert result.decision is PermissionDecision.DENY


def test_safe_command_passes() -> None:
    result = DestructiveCommandGuard().evaluate(
        tool_name="run_command",
        arguments={"argv": ["python", "-V"]},
    )
    assert result is None


def test_non_run_command_passes() -> None:
    result = DestructiveCommandGuard().evaluate(
        tool_name="read_file",
        arguments={"path": "README.md"},
    )
    assert result is None


def test_malformed_argv_passes() -> None:
    result = DestructiveCommandGuard().evaluate(
        tool_name="run_command",
        arguments={"argv": "not-a-list"},
    )
    assert result is None
