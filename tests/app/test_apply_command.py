from pathlib import Path

from baremetal_harness.app import create_app
from baremetal_harness.config import BareMetalHarnessConfig
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.permissions.types import ApprovalResolution


class Approve:
    """Approve everything, or everything except one named operation."""

    def __init__(self, *, deny: str | None = None) -> None:
        self.deny = deny

    async def resolve(self, request):
        approved = request.tool_name != self.deny
        return ApprovalResolution(
            request.request_id, approved, "test" if approved else "denied by test"
        )


async def _app(tmp_path: Path, provider=None, approvals=None):
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    (workspace / "README.md").write_text("original\n")
    return await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=provider or FakeModel([]),
        approval_provider=approvals or Approve(),
    )


def _write_turn(path: str, content: str):
    return (
        ToolCallDelta(
            0, f"c-{path}", "write_file",
            f'{{"path":"{path}","content":"{content}"}}',
        ),
        ResponseCompleted("tool_calls"),
    )


async def test_changes_is_empty_before_the_agent_writes(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    output = (await app.handle_command("/changes")).output
    await app.aclose()

    assert output == "no changes in the sandbox workspace"


async def test_agent_writes_are_visible_but_not_applied(tmp_path: Path) -> None:
    app = await _app(
        tmp_path,
        ScriptedModel((_write_turn("notes.txt", "drafted"),
                       (TextDelta("done"), ResponseCompleted("stop")))),
    )
    try:
        await app.run_prompt("write notes")
        output = (await app.handle_command("/changes")).output
    finally:
        await app.aclose()

    assert "new  notes.txt" in output
    # The real project is untouched until the user applies.
    assert not (tmp_path / "project" / "notes.txt").exists()


async def test_apply_named_path_reaches_the_real_project(tmp_path: Path) -> None:
    app = await _app(
        tmp_path,
        ScriptedModel((_write_turn("notes.txt", "drafted"),
                       (TextDelta("done"), ResponseCompleted("stop")))),
    )
    try:
        await app.run_prompt("write notes")
        output = (await app.handle_command("/apply notes.txt")).output
    finally:
        await app.aclose()

    assert "applied to" in output
    assert (tmp_path / "project" / "notes.txt").read_text() == "drafted"


async def test_apply_all_applies_every_change(tmp_path: Path) -> None:
    app = await _app(
        tmp_path,
        ScriptedModel((_write_turn("a.txt", "A"), _write_turn("b.txt", "B"),
                       (TextDelta("done"), ResponseCompleted("stop")))),
    )
    try:
        await app.run_prompt("write two files")
        await app.handle_command("/apply --all")
    finally:
        await app.aclose()

    assert (tmp_path / "project" / "a.txt").read_text() == "A"
    assert (tmp_path / "project" / "b.txt").read_text() == "B"


async def test_denied_apply_leaves_the_project_untouched(tmp_path: Path) -> None:
    app = await _app(
        tmp_path,
        ScriptedModel((_write_turn("notes.txt", "drafted"),
                       (TextDelta("done"), ResponseCompleted("stop")))),
        # The write itself is allowed; only the apply step is refused.
        approvals=Approve(deny="apply_artifacts"),
    )
    try:
        await app.run_prompt("write notes")
        output = (await app.handle_command("/apply notes.txt")).output
    finally:
        await app.aclose()

    assert "denied" in output
    assert not (tmp_path / "project" / "notes.txt").exists()


async def test_apply_rejects_a_path_the_agent_did_not_change(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    output = (await app.handle_command("/apply nothing.txt")).output
    await app.aclose()

    assert "not changed in the sandbox" in output


async def test_apply_without_argument_shows_usage(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    output = (await app.handle_command("/apply")).output
    await app.aclose()

    assert "usage: /apply" in output
