from collections.abc import Callable
from pathlib import Path

import pytest

from baremetal_harness.cli import repl
from baremetal_harness.cli.repl import _run_application, main
from baremetal_harness.config import BareMetalHarnessConfig, SecretProvider
from baremetal_harness.config_store import ConfigStore


def sequence_input(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)
    return lambda prompt: next(iterator)


def write_config(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o600)


def test_first_tty_start_runs_wizard_then_application(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    received: list[tuple[BareMetalHarnessConfig, SecretProvider]] = []

    status = main(
        ["--config", str(path)],
        environ={},
        input_fn=sequence_input(["https://model.invalid/v1", "demo-model"]),
        secret_input=lambda prompt: "file-secret-1234",
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: (
            received.append((config, secrets)) or 0
        ),
    )

    assert status == 0
    assert path.exists()
    config, secrets = received[0]
    assert config.base_url == "https://model.invalid/v1"
    assert config.model == "demo-model"
    assert not hasattr(config, "api_key")
    assert secrets.get("OPENAI_API_KEY") == "file-secret-1234"


def test_first_non_tty_start_fails_without_prompting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"

    status = main(
        ["--config", str(path)],
        environ={
            "OPENAI_BASE_URL": "https://environment.invalid/v1",
            "OPENAI_MODEL": "environment-model",
            "OPENAI_API_KEY": "environment-secret-5678",
        },
        input_fn=lambda prompt: pytest.fail("must not prompt"),
        secret_input=lambda prompt: pytest.fail("must not prompt"),
        stdin_isatty=lambda: False,
        application_runner=lambda config, secrets: pytest.fail(
            "must not run application"
        ),
    )

    assert status == 2
    assert "baremetal_harness config init" in capsys.readouterr().err
    assert not path.exists()


def test_existing_config_skips_wizard_and_environment_secret_wins(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    assert (
        main(
            ["--config", str(path), "config", "init"],
            input_fn=sequence_input(["https://file.invalid/v1", "file-model"]),
            secret_input=lambda prompt: "file-secret-1234",
            stdin_isatty=lambda: True,
        )
        == 0
    )
    received: list[str | None] = []

    status = main(
        ["--config", str(path)],
        environ={"OPENAI_API_KEY": "environment-secret-5678"},
        input_fn=lambda prompt: pytest.fail("wizard must not run"),
        secret_input=lambda prompt: pytest.fail("wizard must not run"),
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: (
            received.append(secrets.get("OPENAI_API_KEY")) or 0
        ),
    )

    assert status == 0
    assert received == ["environment-secret-5678"]


def test_startup_resolves_runtime_and_secret_from_one_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
base_url = "https://generation-a.invalid/v1"
model = "generation-a-model"
api_key = "generation-a-secret"
""".strip(),
    )
    original_read = ConfigStore.read
    read_count = 0

    def read_once(store: ConfigStore):
        nonlocal read_count
        read_count += 1
        if read_count > 1:
            raise AssertionError("startup must use one config snapshot")
        return original_read(store)

    monkeypatch.setattr(ConfigStore, "read", read_once)
    received: list[tuple[BareMetalHarnessConfig, str | None]] = []

    status = main(
        ["--config", str(path)],
        environ={},
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: (
            received.append((config, secrets.get("OPENAI_API_KEY"))) or 0
        ),
    )

    assert status == 0
    assert read_count == 1
    assert received[0][0].base_url == "https://generation-a.invalid/v1"
    assert received[0][0].model == "generation-a-model"
    assert received[0][1] == "generation-a-secret"


def test_first_run_rechecks_under_coordination_and_skips_wizard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
base_url = "https://other-startup.invalid/v1"
model = "other-startup-model"
api_key = "other-startup-secret"
""".strip(),
    )
    existence_checks = iter([False, True])
    monkeypatch.setattr(
        ConfigStore,
        "exists",
        lambda store: next(existence_checks),
    )
    received: list[tuple[str, str | None]] = []

    status = main(
        ["--config", str(path)],
        environ={},
        input_fn=lambda prompt: pytest.fail("wizard must not run"),
        secret_input=lambda prompt: pytest.fail("wizard must not run"),
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: (
            received.append((config.model, secrets.get("OPENAI_API_KEY"))) or 0
        ),
    )

    assert status == 0
    assert received == [("other-startup-model", "other-startup-secret")]


def test_existing_config_starts_with_environment_secret_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
base_url = "https://file.invalid/v1"
model = "file-model"
""".strip(),
    )
    received: list[str | None] = []

    status = main(
        ["--config", str(path)],
        environ={"OPENAI_API_KEY": "environment-secret-5678"},
        input_fn=lambda prompt: pytest.fail("wizard must not run"),
        secret_input=lambda prompt: pytest.fail("wizard must not run"),
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: (
            received.append(secrets.get("OPENAI_API_KEY")) or 0
        ),
    )

    assert status == 0
    assert received == ["environment-secret-5678"]


def test_empty_environment_secret_falls_back_to_file_secret(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
base_url = "https://file.invalid/v1"
model = "file-model"
api_key = "file-secret-1234"
""".strip(),
    )
    received: list[str | None] = []

    status = main(
        ["--config", str(path)],
        environ={"OPENAI_API_KEY": ""},
        input_fn=lambda prompt: pytest.fail("wizard must not run"),
        secret_input=lambda prompt: pytest.fail("wizard must not run"),
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: (
            received.append(secrets.get("OPENAI_API_KEY")) or 0
        ),
    )

    assert status == 0
    assert received == ["file-secret-1234"]


@pytest.mark.parametrize("error_type", [EOFError, KeyboardInterrupt])
def test_cancelled_first_wizard_creates_no_file_and_reports_safely(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    error_type: type[BaseException],
) -> None:
    path = tmp_path / "config.toml"
    secret = "cancelled-secret-1234"

    status = main(
        ["--config", str(path)],
        environ={},
        input_fn=sequence_input(["https://model.invalid/v1", "demo-model"]),
        secret_input=lambda prompt: (_ for _ in ()).throw(error_type(secret)),
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: pytest.fail(
            "must not run application"
        ),
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "cancelled" in captured.err
    assert secret not in captured.out
    assert secret not in captured.err
    assert not path.exists()


def test_invalid_existing_config_never_runs_wizard_or_application(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    secret = "invalid-file-secret-1234"
    write_config(
        path,
        f'[baremetal_harness]\napi_key = "{secret}"\nmodel = [not-valid\n',
    )

    status = main(
        ["--config", str(path)],
        environ={},
        input_fn=lambda prompt: pytest.fail("wizard must not run"),
        secret_input=lambda prompt: pytest.fail("wizard must not run"),
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: pytest.fail(
            "must not run application"
        ),
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "invalid config file" in captured.err
    assert secret not in captured.out
    assert secret not in captured.err


def test_startup_config_os_error_returns_two_without_exception_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "real-model"\n')
    secret = "startup-permission-secret-1234"

    def fail_read(store: ConfigStore) -> None:
        raise PermissionError(f"cannot read {secret}")

    monkeypatch.setattr(ConfigStore, "read", fail_read)

    status = main(
        ["--config", str(path)],
        environ={},
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: pytest.fail(
            "must not run application"
        ),
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "failed to read configuration" in captured.err
    assert secret not in captured.err


def test_startup_does_not_swallow_unexpected_resolution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "real-model"\n')

    def fail_resolve(*args: object, **kwargs: object) -> BareMetalHarnessConfig:
        raise RuntimeError("resolution programming bug")

    monkeypatch.setattr(repl, "resolve_config", fail_resolve)

    with pytest.raises(RuntimeError, match="resolution programming bug"):
        main(
            ["--config", str(path)],
            environ={},
            stdin_isatty=lambda: True,
            application_runner=lambda config, secrets: 0,
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://model.invalid:not-a-port/v1",
        "https://model.invalid:99999/v1",
    ],
)
def test_startup_rejects_invalid_cli_port_before_state_creation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    write_config(
        path,
        (
            "[baremetal_harness]\n"
            'model = "real-model"\n'
            'base_url = "https://model.invalid/v1"\n'
            'api_key = "file-secret-1234"\n'
        ),
    )

    async def fail_create_app(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid URL must be rejected before create_app")

    monkeypatch.setattr("baremetal_harness.app.create_app", fail_create_app)

    status = main(
        [
            "--config",
            str(path),
            "--data-dir",
            str(data_dir),
            "--workspace",
            str(workspace),
            "--base-url",
            base_url,
        ],
        environ={},
        stdin_isatty=lambda: True,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "base_url" in captured.err
    assert "file-secret-1234" not in captured.err
    assert not data_dir.exists()
    assert not workspace.exists()


def test_cli_runtime_values_override_file_and_environment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
base_url = "https://file.invalid/v1"
model = "file-model"
api_key = "file-secret-1234"
""".strip(),
    )
    received: list[BareMetalHarnessConfig] = []

    status = main(
        [
            "--config",
            str(path),
            "--base-url",
            "https://cli.invalid/v1",
            "--model",
            "cli-model",
        ],
        environ={
            "OPENAI_BASE_URL": "https://environment.invalid/v1",
            "OPENAI_MODEL": "environment-model",
        },
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: received.append(config) or 0,
    )

    assert status == 0
    assert received[0].base_url == "https://cli.invalid/v1"
    assert received[0].model == "cli-model"


def test_fake_model_failure_is_safe_and_explains_both_fixes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.toml"
    secret = "fake-model-secret-1234"
    write_config(
        path,
        f"""
[baremetal_harness]
base_url = "https://file.invalid/v1"
model = "fake"
api_key = "{secret}"
""".strip(),
    )

    status = main(
        ["--config", str(path)],
        environ={},
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: pytest.fail(
            "must not run application"
        ),
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "baremetal_harness config set model <name>" in captured.err
    assert "OPENAI_MODEL" in captured.err
    assert secret not in captured.out
    assert secret not in captured.err


@pytest.mark.parametrize(
    ("contents", "expected_message"),
    [
        (
            '[baremetal_harness]\nmodel = "real-model"\napi_key = "file-secret-1234"\n',
            "base_url",
        ),
        (
            (
                '[baremetal_harness]\nmodel = "real-model"\n'
                'base_url = "https://model.invalid/v1"\n'
            ),
            "API key",
        ),
    ],
)
def test_default_runner_preflight_rejects_missing_runtime_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
    expected_message: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, contents)

    async def fail_create_app(*args: object, **kwargs: object) -> None:
        pytest.fail("preflight must run before create_app")

    monkeypatch.setattr("baremetal_harness.app.create_app", fail_create_app)

    status = main(
        ["--config", str(path)],
        environ={},
        stdin_isatty=lambda: True,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert expected_message in captured.err
    assert "file-secret-1234" not in captured.out
    assert "file-secret-1234" not in captured.err


def test_default_runner_reports_expected_initialization_failure_safely(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
model = "real-model"
base_url = "https://model.invalid/v1"
api_key = "file-secret-1234"
""".strip(),
    )

    async def fail_create_app(*args: object, **kwargs: object) -> None:
        raise repl.ApplicationConfigurationError("sandbox unavailable")

    monkeypatch.setattr("baremetal_harness.app.create_app", fail_create_app)

    status = main(
        ["--config", str(path)],
        environ={},
        stdin_isatty=lambda: True,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "sandbox unavailable" in captured.err
    assert "file-secret-1234" not in captured.err


def test_default_runner_does_not_swallow_unexpected_programming_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
model = "real-model"
base_url = "https://model.invalid/v1"
api_key = "file-secret-1234"
""".strip(),
    )

    async def fail_create_app(*args: object, **kwargs: object) -> None:
        raise RuntimeError("programming bug")

    monkeypatch.setattr("baremetal_harness.app.create_app", fail_create_app)

    with pytest.raises(RuntimeError, match="programming bug"):
        main(
            ["--config", str(path)],
            environ={},
            stdin_isatty=lambda: True,
        )


def test_custom_runner_keeps_direct_behavior_without_default_preflight(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "real-model"\n')
    received: list[BareMetalHarnessConfig] = []

    status = main(
        ["--config", str(path)],
        environ={},
        stdin_isatty=lambda: True,
        application_runner=lambda config, secrets: received.append(config) or 7,
    )

    assert status == 7
    assert received[0].base_url is None


def test_custom_runner_exception_is_not_swallowed(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "real-model"\n')

    def fail_runner(
        config: BareMetalHarnessConfig,
        secrets: SecretProvider,
    ) -> int:
        raise RuntimeError("custom runner failure")

    with pytest.raises(RuntimeError, match="custom runner failure"):
        main(
            ["--config", str(path)],
            environ={},
            stdin_isatty=lambda: True,
            application_runner=fail_runner,
        )


def test_run_application_closes_app_after_interactive_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class RecordingApp:
        async def start_scheduler(self) -> None:
            pass

        async def aclose(self) -> None:
            closed.append(True)

    async def create_app(
        config: BareMetalHarnessConfig,
        *,
        secret_provider: SecretProvider,
    ) -> RecordingApp:
        return RecordingApp()

    async def run_interactive(app_repl: repl.AppRepl) -> None:
        assert isinstance(app_repl.app, RecordingApp)

    monkeypatch.setattr("baremetal_harness.app.create_app", create_app)
    monkeypatch.setattr(repl, "run_app_interactive", run_interactive)

    status = _run_application(
        BareMetalHarnessConfig(tmp_path / "data", tmp_path / "workspace"),
        lambda_secret_provider(),
    )

    assert status == 0
    assert closed == [True]


def test_run_application_closes_app_after_interactive_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class RecordingApp:
        async def start_scheduler(self) -> None:
            pass

        async def aclose(self) -> None:
            closed.append(True)

    async def create_app(
        config: BareMetalHarnessConfig,
        *,
        secret_provider: SecretProvider,
    ) -> RecordingApp:
        return RecordingApp()

    async def fail_interactive(app_repl: repl.AppRepl) -> None:
        raise RuntimeError("interactive failure")

    monkeypatch.setattr("baremetal_harness.app.create_app", create_app)
    monkeypatch.setattr(repl, "run_app_interactive", fail_interactive)

    with pytest.raises(RuntimeError, match="interactive failure"):
        _run_application(
            BareMetalHarnessConfig(tmp_path / "data", tmp_path / "workspace"),
            lambda_secret_provider(),
        )

    assert closed == [True]


def lambda_secret_provider() -> SecretProvider:
    class EmptySecretProvider:
        def get(self, name: str) -> str | None:
            return None

    return EmptySecretProvider()
