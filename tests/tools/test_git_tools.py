import subprocess
from pathlib import Path

import pytest

from baremetal_harness.permissions.policy import DefaultPermissionPolicy
from baremetal_harness.permissions.types import PermissionDecision
from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.tools.builtin.git import make_git_tools
from baremetal_harness.tools.types import ToolContext
from baremetal_harness.workspace.paths import WorkspaceEscape


def _git(repository: Path, *argv: str) -> None:
    subprocess.run(
        ["git", *argv],
        cwd=repository,
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("first\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "initial commit")
    return tmp_path


def _tools() -> dict:
    return {
        tool.spec.name: tool for tool in make_git_tools(ProcessSandbox())
    }


def _context(repository: Path) -> ToolContext:
    return ToolContext("run-1", "session-1", repository)


async def test_status_reports_a_dirty_working_tree(repository: Path) -> None:
    (repository / "README.md").write_text("changed\n")

    output = await _tools()["git_status"].handler({}, _context(repository))

    assert "## main" in output
    assert "README.md" in output


async def test_log_lists_commits(repository: Path) -> None:
    output = await _tools()["git_log"].handler(
        {"limit": 5}, _context(repository)
    )

    assert "initial commit" in output


async def test_diff_shows_unstaged_changes(repository: Path) -> None:
    (repository / "README.md").write_text("second\n")

    output = await _tools()["git_diff"].handler({}, _context(repository))

    assert "-first" in output
    assert "+second" in output


async def test_show_renders_one_commit(repository: Path) -> None:
    output = await _tools()["git_show"].handler(
        {"revision": "HEAD"}, _context(repository)
    )

    assert "initial commit" in output
    assert "README.md" in output


async def test_revision_cannot_smuggle_an_option(repository: Path) -> None:
    with pytest.raises(ValueError, match="revision"):
        await _tools()["git_show"].handler(
            {"revision": "--upload-pack=touch /tmp/pwned"},
            _context(repository),
        )


async def test_path_cannot_escape_the_workspace(repository: Path) -> None:
    with pytest.raises(WorkspaceEscape):
        await _tools()["git_log"].handler(
            {"path": "../../../etc/passwd"}, _context(repository)
        )


async def test_limit_is_bounded(repository: Path) -> None:
    with pytest.raises(ValueError, match="limit"):
        await _tools()["git_log"].handler(
            {"limit": 100_000}, _context(repository)
        )


async def test_non_repository_reports_a_readable_failure(tmp_path: Path) -> None:
    output = await _tools()["git_status"].handler({}, _context(tmp_path))

    assert output.startswith("git status failed:")


def test_read_only_git_does_not_require_approval() -> None:
    for tool in make_git_tools(ProcessSandbox()):
        result = DefaultPermissionPolicy().evaluate(
            tool_name=tool.spec.name,
            capabilities=tool.spec.capabilities,
            arguments={},
        )
        assert result.decision is PermissionDecision.ALLOW, tool.spec.name
        assert result.reason == "read-only inspection tool"


def test_write_capable_shell_still_requires_approval() -> None:
    from baremetal_harness.sandbox.process import ProcessSandbox as Sandbox
    from baremetal_harness.tools.builtin.shell import make_run_command_tool

    tool = make_run_command_tool(Sandbox())
    result = DefaultPermissionPolicy().evaluate(
        tool_name=tool.spec.name,
        capabilities=tool.spec.capabilities,
        arguments={"argv": ["echo", "hi"]},
    )

    assert result.decision is PermissionDecision.ASK
