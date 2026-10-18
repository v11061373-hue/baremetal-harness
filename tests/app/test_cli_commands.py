from pathlib import Path

from baremetal_harness.app import create_app
from baremetal_harness.cli.commands import CommandRouter
from baremetal_harness.cli.repl import AppRepl
from baremetal_harness.config import BareMetalHarnessConfig, load_config
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.fake import FakeModel


def test_unknown_command_returns_hint_without_model_dispatch() -> None:
    result = CommandRouter().handle("/unknown")
    assert result.handled is True
    assert "help" in result.output.casefold()
    assert result.exit_requested is False


def test_help_lists_final_commands() -> None:
    output = CommandRouter().handle("/help").output
    assert "/resume" in output
    assert "/memory" in output
    assert "/sandbox" in output


async def test_app_command_router_queries_real_components(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel((TextDelta("hello"), ResponseCompleted("stop"))),
    )
    result = await app.run_prompt("hi")

    sessions = await app.handle_command("/sessions")
    sandbox = await app.handle_command("/sandbox")
    metrics = await app.handle_command("/metrics")

    assert result.session_id in sessions.output
    assert "process" in sandbox.output
    assert '"model_requests":1' in metrics.output


async def test_non_command_is_not_consumed_by_app_router(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel(()),
    )

    result = await app.handle_command("hello")

    assert result.handled is False


def test_config_precedence_is_toml_then_environment_then_cli(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[baremetal_harness]
workspace = "/from-toml"
model = "toml-model"
base_url = "https://toml.invalid/v1"
api_key = "file-secret-1234"
max_turns = 4
""".strip()
    )
    config_file.chmod(0o600)

    config = load_config(
        config_file,
        environ={
            "BAREMETAL_HARNESS_WORKSPACE": "/from-environment",
            "OPENAI_MODEL": "environment-model",
            "OPENAI_BASE_URL": "https://environment.invalid/v1",
        },
        overrides={
            "model": "cli-model",
            "base_url": "https://cli.invalid/v1",
            "max_turns": 9,
        },
    )

    assert config.workspace == Path("/from-environment")
    assert config.model == "cli-model"
    assert config.base_url == "https://cli.invalid/v1"
    assert config.max_turns == 9
    assert not hasattr(config, "api_key")


async def test_app_repl_routes_commands_without_calling_model(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    provider = FakeModel((TextDelta("hello"), ResponseCompleted("stop")))
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=provider,
    )
    output: list[str] = []
    repl = AppRepl(app, write=output.append)

    await repl.process("/unknown")
    assert provider.requests == []

    await repl.process("hi")
    assert len(provider.requests) == 1
    assert "".join(output) == "unknown command; use /helphello"


async def test_app_repl_streams_text_deltas_as_they_arrive(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel(
            (
                TextDelta("hello "),
                TextDelta("there"),
                ResponseCompleted("stop"),
            )
        ),
    )
    output: list[str] = []
    repl = AppRepl(app, write=output.append)

    await repl.process("hi")

    assert output == ["hello ", "there"]


async def test_app_repl_default_terminal_writer_keeps_stream_on_one_line(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel(
            (
                TextDelta("hello "),
                TextDelta("there"),
                ResponseCompleted("stop"),
            )
        ),
    )

    await AppRepl(app).process("hi")

    assert capsys.readouterr().out == "hello there"


async def test_app_repl_default_terminal_writer_keeps_command_line_break(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel(()),
    )

    await AppRepl(app).process("/unknown")

    assert capsys.readouterr().out == "unknown command; use /help\n"


async def test_app_repl_accepts_multiple_prompts(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    provider = FakeModel((TextDelta("ok"), ResponseCompleted("stop")))
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=provider,
    )
    repl = AppRepl(app, write=lambda text: None)

    await repl.process("first")
    await repl.process("second")

    assert len(provider.requests) == 2
    assert [message.role for message in provider.requests[1].messages] == [
        "user",
        "assistant",
        "user",
    ]

    await repl.process("/clear")
    await repl.process("after clear")

    assert [message.role for message in provider.requests[2].messages] == ["user"]
