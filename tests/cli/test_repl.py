import pytest

from baremetal_harness.cli.config import ReplConfig
from baremetal_harness.cli.repl import Repl
from baremetal_harness.core.errors import ModelProtocolError
from baremetal_harness.core.messages import (
    Message,
    ResponseCompleted,
    TextContent,
    TextDelta,
)
from baremetal_harness.model.fake import FakeModel


async def test_repl_turn_streams_text_and_appends_history() -> None:
    output: list[str] = []
    repl = Repl(
        provider=FakeModel([TextDelta("hello"), ResponseCompleted("stop")]),
        model="fake",
        write=output.append,
    )

    await repl.run_turn("hi")

    assert "".join(output) == "hello"
    assert [message.role for message in repl.messages] == ["user", "assistant"]


async def test_incomplete_turn_does_not_commit_messages() -> None:
    repl = Repl(FakeModel([TextDelta("partial")]), "fake", write=lambda text: None)

    with pytest.raises(ModelProtocolError, match="without completion"):
        await repl.run_turn("hi")

    assert repl.messages == []


def test_clear_removes_history() -> None:
    repl = Repl(FakeModel([]), "fake", write=lambda text: None)
    repl.messages.append(Message("user", (TextContent("hi"),)))

    assert repl.handle_command("/clear") is True
    assert repl.messages == []


@pytest.mark.parametrize("command", ["/exit", "/quit"])
def test_exit_commands_are_handled(command: str) -> None:
    repl = Repl(FakeModel([]), "fake", write=lambda text: None)

    assert repl.handle_command(command) is True


def test_config_reports_missing_environment(monkeypatch) -> None:
    for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit, match="OPENAI_BASE_URL"):
        ReplConfig.from_environment()
