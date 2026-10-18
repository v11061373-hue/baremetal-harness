import logging
from pathlib import Path

import pytest

from baremetal_harness.core.messages import ToolCall
from baremetal_harness.tools.executor import ToolExecutor
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import (
    RegisteredTool,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)
from baremetal_harness.workspace.paths import WorkspaceEscape

NO_ARGS = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def _registry(handler) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(ToolSpec("boom", "fails", NO_ARGS, ToolCapabilities()), handler)
    )
    return registry


async def _run(handler, tmp_path: Path):
    return await ToolExecutor(_registry(handler)).execute(
        ToolCall("call-1", "boom", {}),
        ToolContext("run-1", "session-1", tmp_path),
    )


async def test_deliberate_validation_error_reaches_the_model(tmp_path: Path) -> None:
    async def handler(arguments, context):
        raise ValueError("limit must be between 1 and 200")

    result = await _run(handler, tmp_path)

    assert result.is_error
    # The model needs this to correct its next call.
    assert "limit must be between 1 and 200" in result.output


async def test_workspace_escape_is_reported(tmp_path: Path) -> None:
    async def handler(arguments, context):
        raise WorkspaceEscape("path escapes the workspace")

    result = await _run(handler, tmp_path)

    assert "path escapes the workspace" in result.output


async def test_unexpected_error_reveals_only_its_type(tmp_path: Path) -> None:
    secret = "/Users/someone/.ssh/id_rsa"

    async def handler(arguments, context):
        raise OSError(f"cannot read {secret}")

    result = await _run(handler, tmp_path)

    assert "OSError" in result.output
    assert secret not in result.output


async def test_reason_is_truncated(tmp_path: Path) -> None:
    async def handler(arguments, context):
        raise ValueError("x" * 5000)

    result = await _run(handler, tmp_path)

    assert len(result.output) < 400


async def test_whitespace_in_a_reason_is_collapsed(tmp_path: Path) -> None:
    async def handler(arguments, context):
        raise ValueError("first line\n\n  second line")

    result = await _run(handler, tmp_path)

    assert "first line second line" in result.output


async def test_operator_still_gets_the_traceback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(arguments, context):
        raise OSError("cannot read /Users/someone/.ssh/id_rsa")

    with caplog.at_level(logging.ERROR, logger="baremetal_harness.tools.executor"):
        await _run(handler, tmp_path)

    assert "cannot read" in caplog.text
    assert "run-1" in caplog.text


async def test_empty_value_error_falls_back_to_the_type(tmp_path: Path) -> None:
    async def handler(arguments, context):
        raise ValueError()

    result = await _run(handler, tmp_path)

    assert "ValueError" in result.output
