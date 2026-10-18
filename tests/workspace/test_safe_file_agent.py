import sys
from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.tools.builtin.files import make_file_tools
from baremetal_harness.tools.builtin.shell import make_run_command_tool
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.workspace.session import WorkspaceSession


async def test_agent_changes_only_sandbox_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "workspace-secret-value"
    monkeypatch.setenv("SECRET_TOKEN", secret)
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("original")
    session = WorkspaceSession.create(tmp_path / "sandboxes", source)
    results = []
    registry = ToolRegistry()
    for tool in make_file_tools():
        registry.register(tool)
    registry.register(
        make_run_command_tool(
            ProcessSandbox(),
            allowed_environment=("PATH",),
            result_sink=results.append,
        )
    )
    provider = ScriptedModel(
        (
            (
                ToolCallDelta(
                    0,
                    "write-1",
                    "write_file",
                    '{"path":"notes.txt","content":"sandbox only"}',
                ),
                ResponseCompleted("tool_calls"),
            ),
            (
                ToolCallDelta(
                    0,
                    "run-1",
                    "run_command",
                    (
                        '{"argv":'
                        f'["{sys.executable}","-c",'
                        '"from pathlib import Path; '
                        "Path('command.txt').write_text('ok')\"]}"
                    ),
                ),
                ResponseCompleted("tool_calls"),
            ),
            (TextDelta("done"), ResponseCompleted("stop")),
        )
    )

    result = await AgentLoop(
        provider,
        "fake",
        tools=registry,
        workspace=session.workspace,
    ).run("write files safely")

    assert result.status is RunStatus.COMPLETED
    assert (session.workspace / "notes.txt").read_text() == "sandbox only"
    assert (session.workspace / "command.txt").read_text() == "ok"
    assert not (source / "notes.txt").exists()
    assert not (source / "command.txt").exists()
    assert results[0].changed_paths == (Path("command.txt"),)
    assert results[0].warnings == (
        "network isolation is not enforced by process backend",
    )
    assert secret not in repr(result)
    assert secret not in repr(results)


async def test_file_tool_returns_public_error_for_escape(tmp_path: Path) -> None:
    registry = ToolRegistry()
    for tool in make_file_tools():
        registry.register(tool)
    provider = ScriptedModel(
        (
            (
                ToolCallDelta(
                    0,
                    "write-escape",
                    "write_file",
                    '{"path":"../escape","content":"blocked"}',
                ),
                ResponseCompleted("tool_calls"),
            ),
            (TextDelta("blocked"), ResponseCompleted("stop")),
        )
    )

    result = await AgentLoop(
        provider,
        "fake",
        tools=registry,
        workspace=tmp_path,
    ).run("escape")

    tool_result = result.messages[2].content[0]
    assert tool_result.is_error is True
    # The model is told why so it can correct itself, but the resolved
    # filesystem path never reaches it.
    assert "escapes the workspace" in tool_result.output
    assert str(tmp_path) not in tool_result.output
    assert not (tmp_path.parent / "escape").exists()
