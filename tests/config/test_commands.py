from collections.abc import Callable
from pathlib import Path

import pytest

from baremetal_harness.cli import repl
from baremetal_harness.cli.repl import main
from baremetal_harness.config_store import ConfigStore


def sequence_input(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)
    return lambda prompt: next(iterator)


def write_config(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o600)


def test_config_path_uses_explicit_path_without_creating_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "custom.toml"

    status = main(["--config", str(path), "config", "path"])

    assert status == 0
    assert capsys.readouterr().out.strip() == str(path.absolute())
    assert not path.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["config"],
        ["config", "get"],
        ["config", "set"],
        ["config", "unset"],
        ["config", "unknown"],
        ["config", "show", "extra"],
        ["config", "get", "model", "extra"],
        ["config", "unset", "model", "extra"],
        ["config", "path", "extra"],
    ],
)
def test_config_parser_errors_return_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    status = main(["--config", str(tmp_path / "config.toml"), *arguments])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "usage:" in captured.err
    assert "error:" in captured.err


@pytest.mark.parametrize("arguments", [["--help"], ["config", "--help"]])
def test_help_returns_zero(
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    status = main(arguments)

    captured = capsys.readouterr()
    assert status == 0
    assert "usage:" in captured.out
    assert captured.err == ""


def test_invalid_config_path_construction_returns_safe_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    unsafe_path = "~must_not_echo_secret_user/config.toml"

    status = main(["--config", unsafe_path, "config", "path"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "invalid config path" in captured.err
    assert unsafe_path not in captured.err
    assert "must_not_echo_secret_user" not in captured.err


def test_config_show_and_get_redact_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    secret = "file-secret-1234"

    assert main(["--config", str(path), "config", "set", "model", "demo"]) == 0
    assert (
        main(
            ["--config", str(path), "config", "set", "api_key"],
            stdin_isatty=lambda: True,
            secret_input=lambda prompt: secret,
        )
        == 0
    )
    capsys.readouterr()

    assert main(["--config", str(path), "config", "show"]) == 0
    show_output = capsys.readouterr().out
    assert secret not in show_output
    assert "********1234" in show_output

    assert main(["--config", str(path), "config", "get", "api_key"]) == 0
    get_output = capsys.readouterr().out
    assert secret not in get_output
    assert get_output.strip() == "********1234"


def test_config_show_stdout_matches_display_golden(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    store.set("model", "demo")

    status = main(["--config", str(path), "config", "show"])

    assert status == 0
    assert capsys.readouterr().out == (
        "# BareMetal Harness configuration display (display-only; not writable TOML)\n"
        f"# path = {path}\n"
        "# exists = true\n"
        "\n"
        "[baremetal_harness]\n"
        f'data_dir = "{Path.home() / ".baremetal_harness"}"\n'
        f'workspace = "{Path.cwd()}"\n'
        'model = "demo"\n'
        'base_url = "not configured"\n'
        'api_key = "not configured"\n'
        "require_strong_sandbox = false\n"
        'docker_image = "python:3.12-slim"\n'
        "max_turns = 16\n"
        "max_tool_calls = 32\n"
        "context_tokens = 32000\n"
        "reserve_output_tokens = 4000\n"
    )


@pytest.mark.parametrize("action", ["get", "set", "unset"])
def test_unknown_config_key_returns_validation_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    action: str,
) -> None:
    path = tmp_path / "config.toml"
    arguments = ["--config", str(path), "config", action, "unknown"]
    if action == "set":
        arguments.append("value")

    status = main(arguments)

    captured = capsys.readouterr()
    assert status == 2
    assert "unknown config field" in captured.err
    assert "unknown" in captured.err
    assert captured.out == ""
    assert not path.exists()


def test_normal_set_requires_exactly_one_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"

    missing_status = main(["--config", str(path), "config", "set", "model"])
    extra_status = main(
        [
            "--config",
            str(path),
            "config",
            "set",
            "model",
            "first",
            "second",
        ]
    )

    captured = capsys.readouterr()
    assert missing_status == 2
    assert extra_status == 2
    assert "value is required for model" in captured.err
    assert "exactly one value is required for model" in captured.err
    assert not path.exists()


@pytest.mark.parametrize(
    "source",
    ["1.9", "inf", "nan", "1e3", "+1", "-1", " 1", "1 ", "01"],
)
def test_cli_integer_values_reject_noncanonical_strings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source: str,
) -> None:
    path = tmp_path / "config.toml"

    status = main(
        [
            "--config",
            str(path),
            "config",
            "set",
            "max_turns",
            source,
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "max_turns must be a positive integer" in captured.err
    assert not path.exists()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://model.invalid:not-a-port/v1",
        "https://model.invalid:99999/v1",
    ],
)
def test_cli_base_url_rejects_invalid_ports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    base_url: str,
) -> None:
    path = tmp_path / "config.toml"

    status = main(
        [
            "--config",
            str(path),
            "config",
            "set",
            "base_url",
            base_url,
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "base_url" in captured.err
    assert not path.exists()


def test_api_key_positional_arguments_are_rejected_without_writing_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    secret = "must-not-reach-output-1234"

    status = main(
        [
            "--config",
            str(path),
            "config",
            "set",
            "api_key",
            secret,
            "--still-secret",
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert secret not in captured.out
    assert secret not in captured.err
    assert "--still-secret" not in captured.out
    assert "--still-secret" not in captured.err
    assert "must be entered interactively" in captured.err
    assert not path.exists()


def test_non_tty_api_key_set_fails_without_prompting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"

    status = main(
        ["--config", str(path), "config", "set", "api_key"],
        stdin_isatty=lambda: False,
        secret_input=lambda prompt: pytest.fail("must not prompt"),
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "requires a TTY" in captured.err
    assert captured.out == ""
    assert not path.exists()


def test_invalid_set_preserves_file_bytes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"

    assert main(["--config", str(path), "config", "set", "context_tokens", "100"]) == 2

    assert not path.exists()
    assert "context_tokens" in capsys.readouterr().err


def test_set_get_and_idempotent_unset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"

    assert (
        main(
            [
                "--config",
                str(path),
                "config",
                "set",
                "require_strong_sandbox",
                "true",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--config",
                str(path),
                "config",
                "get",
                "require_strong_sandbox",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.splitlines()[-1] == "true"

    assert main(["--config", str(path), "config", "unset", "model"]) == 0
    assert main(["--config", str(path), "config", "unset", "model"]) == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "unset model",
        "unset model",
    ]


def test_init_command_runs_tty_wizard(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    secret = "wizard-secret-1234"

    status = main(
        ["--config", str(path), "config", "init"],
        input_fn=sequence_input(["https://model.invalid/v1", "demo-model"]),
        secret_input=lambda prompt: secret,
        stdin_isatty=lambda: True,
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "configuration saved" in captured.out
    assert secret not in captured.out
    assert secret not in captured.err
    assert secret in path.read_text()


def test_init_command_does_not_use_first_run_coordination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"

    def fail_coordination(store: ConfigStore) -> None:
        raise AssertionError("config init must not use first-run coordination")

    monkeypatch.setattr(
        ConfigStore,
        "coordinate_first_run",
        fail_coordination,
    )

    status = main(
        ["--config", str(path), "config", "init"],
        input_fn=sequence_input(["https://model.invalid/v1", "demo-model"]),
        secret_input=lambda prompt: "file-secret-1234",
        stdin_isatty=lambda: True,
    )

    assert status == 0
    assert ConfigStore(path).read().get("model") == "demo-model"


def test_non_tty_init_returns_interaction_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"

    status = main(
        ["--config", str(path), "config", "init"],
        input_fn=lambda prompt: pytest.fail("must not prompt"),
        secret_input=lambda prompt: pytest.fail("must not prompt"),
        stdin_isatty=lambda: False,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "config initialization requires a TTY" in captured.err
    assert captured.out == ""
    assert not path.exists()


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, EOFError])
def test_init_cancellation_returns_two_without_creating_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    error_type: type[BaseException],
) -> None:
    path = tmp_path / "config.toml"

    def cancel(prompt: str) -> str:
        raise error_type()

    status = main(
        ["--config", str(path), "config", "init"],
        input_fn=cancel,
        secret_input=lambda prompt: pytest.fail("must not prompt"),
        stdin_isatty=lambda: True,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "cancelled" in captured.err
    assert captured.out == ""
    assert not path.exists()


def test_invalid_config_file_produces_safe_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    secret = "invalid-file-secret-1234"
    write_config(path, f'[baremetal_harness]\napi_key = "{secret}"\nmodel = [not-valid\n')

    status = main(["--config", str(path), "config", "show"])

    captured = capsys.readouterr()
    assert status == 2
    assert "invalid config file" in captured.err
    assert secret not in captured.out
    assert secret not in captured.err


@pytest.mark.parametrize("action", ["show", "get"])
def test_config_read_os_errors_return_two_without_exception_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    secret = "permission-secret-1234"

    def fail_read(store: ConfigStore) -> None:
        raise PermissionError(f"cannot read {secret}")

    monkeypatch.setattr(ConfigStore, "read", fail_read)
    arguments = ["config", action]
    if action == "get":
        arguments.append("model")

    status = main(["--config", str(tmp_path / "config.toml"), *arguments])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "failed to read configuration" in captured.err
    assert secret not in captured.err


def test_api_key_validation_exception_does_not_reveal_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    secret = "mutation-secret-1234"

    def fail_set(
        store: ConfigStore,
        field: str,
        value: object,
    ) -> None:
        raise ValueError(f"rejected secret: {secret}")

    monkeypatch.setattr(ConfigStore, "set", fail_set)

    status = main(
        ["--config", str(path), "config", "set", "api_key"],
        stdin_isatty=lambda: True,
        secret_input=lambda prompt: secret,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert secret not in captured.out
    assert secret not in captured.err
    assert not path.exists()


def test_secret_prompt_cancellation_preserves_existing_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    store.initialize(
        base_url="https://before.invalid/v1",
        model="before-model",
        api_key="before-secret-1234",
    )
    original = path.read_bytes()
    prompts: list[str] = []

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return {
            "Base URL [https://before.invalid/v1]: ": ("https://after.invalid/v1"),
            "Model [before-model]: ": "after-model",
        }[prompt]

    def cancel_secret_input(prompt: str) -> str:
        prompts.append(prompt)
        raise KeyboardInterrupt()

    status = main(
        ["--config", str(path), "config", "init"],
        input_fn=input_fn,
        secret_input=cancel_secret_input,
        stdin_isatty=lambda: True,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert prompts == [
        "Base URL [https://before.invalid/v1]: ",
        "Model [before-model]: ",
        "API key: ",
    ]
    assert "cancelled" in captured.err
    assert "before-secret-1234" not in captured.out
    assert "before-secret-1234" not in captured.err
    assert path.read_bytes() == original


def test_path_error_and_persistence_error_return_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    path.mkdir()

    assert main(["--config", str(path), "config", "show"]) == 2
    assert "regular file" in capsys.readouterr().err

    path.rmdir()

    def fail_replace(
        source: Path,
        target: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        raise OSError("injected failure")

    monkeypatch.setattr("os.replace", fail_replace)
    assert main(["--config", str(path), "config", "set", "model", "demo"]) == 2
    assert "failed to persist config" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "secret"),
    [
        (["config", "show"], "show-secret-1234"),
        (["config", "get", "api_key"], "get-secret-1234"),
        (["config", "unset", "api_key"], "unset-secret-1234"),
    ],
)
def test_config_output_never_reveals_file_api_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    secret: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, f'[baremetal_harness]\napi_key = "{secret}"\n')

    status = main(["--config", str(path), *arguments])

    captured = capsys.readouterr()
    assert status == 0
    assert secret not in captured.out
    assert secret not in captured.err


def test_config_command_never_runs_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolve_config(*args: object, **kwargs: object) -> None:
        raise AssertionError("resolve_config must not run")

    async def fail_create_app(*args: object, **kwargs: object) -> None:
        raise AssertionError("create_app must not run")

    monkeypatch.setattr(repl, "resolve_config", fail_resolve_config)
    monkeypatch.setattr("baremetal_harness.app.create_app", fail_create_app)

    status = main(
        ["--config", str(tmp_path / "config.toml"), "config", "show"],
        application_runner=lambda config, secrets: pytest.fail(
            "application runner must not run"
        ),
    )

    assert status == 0
