from collections.abc import Callable
from pathlib import Path

import pytest

from baremetal_harness.cli.config_wizard import (
    ConfigInteractionError,
    run_config_wizard,
)
from baremetal_harness.config_store import ConfigStore


def sequence_input(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)
    return lambda prompt: next(iterator)


def test_first_time_wizard_writes_minimal_config(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    output: list[str] = []
    prompts: list[str] = []
    secret_prompts: list[str] = []
    values = iter(["https://model.invalid/v1", "demo-model"])

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return next(values)

    def secret_input(prompt: str) -> str:
        secret_prompts.append(prompt)
        return "file-secret-1234"

    run_config_wizard(
        store,
        input_fn=input_fn,
        secret_input=secret_input,
        write=output.append,
        is_tty=lambda: True,
    )

    document = store.read()
    assert document.get("base_url") == "https://model.invalid/v1"
    assert document.get("model") == "demo-model"
    assert document.get("api_key") == "file-secret-1234"
    assert document.get("workspace") == Path(".")
    assert prompts == ["Base URL: ", "Model: "]
    assert secret_prompts == ["API key: "]
    assert "file-secret-1234" not in "".join(output)


def test_non_tty_wizard_fails_without_creating_file(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")

    with pytest.raises(ConfigInteractionError, match="TTY"):
        run_config_wizard(
            store,
            input_fn=lambda prompt: pytest.fail("must not prompt"),
            secret_input=lambda prompt: pytest.fail("must not prompt"),
            write=lambda text: pytest.fail("must not write"),
            is_tty=lambda: False,
        )

    assert not store.path.exists()


def test_blank_reconfiguration_values_keep_existing_values(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.initialize(
        base_url="https://before.invalid/v1",
        model="before-model",
        api_key="before-secret-1234",
    )
    secret_prompts: list[str] = []
    output: list[str] = []

    def secret_input(prompt: str) -> str:
        secret_prompts.append(prompt)
        return ""

    run_config_wizard(
        store,
        input_fn=sequence_input(["", ""]),
        secret_input=secret_input,
        write=output.append,
        is_tty=lambda: True,
    )

    document = store.read()
    assert document.get("base_url") == "https://before.invalid/v1"
    assert document.get("model") == "before-model"
    assert document.get("api_key") == "before-secret-1234"
    assert secret_prompts == ["API key: "]
    assert "before-secret-1234" not in "".join(output)


def test_blank_reconfiguration_preserves_concurrent_field_updates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    store.initialize(
        base_url="https://before.invalid/v1",
        model="before-model",
        api_key="before-secret-1234",
    )

    def concurrent_update_then_blank(prompt: str) -> str:
        ConfigStore(path).initialize(
            base_url="https://concurrent.invalid/v1",
            model="concurrent-model",
            api_key="concurrent-secret-5678",
        )
        return ""

    run_config_wizard(
        store,
        input_fn=sequence_input(["", ""]),
        secret_input=concurrent_update_then_blank,
        write=lambda text: None,
        is_tty=lambda: True,
    )

    document = store.read()
    assert document.get("base_url") == "https://concurrent.invalid/v1"
    assert document.get("model") == "concurrent-model"
    assert document.get("api_key") == "concurrent-secret-5678"


def test_invalid_base_url_retries_only_base_url(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    prompts: list[str] = []
    secret_prompts: list[str] = []
    output: list[str] = []
    values = iter(["rejected-base-value", "https://model.invalid/v1", "demo-model"])

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return next(values)

    def secret_input(prompt: str) -> str:
        secret_prompts.append(prompt)
        return "file-secret-1234"

    run_config_wizard(
        store,
        input_fn=input_fn,
        secret_input=secret_input,
        write=output.append,
        is_tty=lambda: True,
    )

    assert prompts == ["Base URL: ", "Base URL: ", "Model: "]
    assert secret_prompts == ["API key: "]
    assert "rejected-base-value" not in "".join(output)


def test_invalid_model_retries_only_model(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    prompts: list[str] = []
    secret_prompts: list[str] = []
    values = iter(["https://model.invalid/v1", "   ", "demo-model"])

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return next(values)

    def secret_input(prompt: str) -> str:
        secret_prompts.append(prompt)
        return "file-secret-1234"

    run_config_wizard(
        store,
        input_fn=input_fn,
        secret_input=secret_input,
        write=lambda text: None,
        is_tty=lambda: True,
    )

    assert prompts == ["Base URL: ", "Model: ", "Model: "]
    assert secret_prompts == ["API key: "]


def test_invalid_api_key_retries_only_api_key_without_exposure(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    prompts: list[str] = []
    secret_prompts: list[str] = []
    output: list[str] = []
    values = iter(["https://model.invalid/v1", "demo-model"])
    secrets = iter(["   ", "file-secret-5678"])

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return next(values)

    def secret_input(prompt: str) -> str:
        secret_prompts.append(prompt)
        return next(secrets)

    run_config_wizard(
        store,
        input_fn=input_fn,
        secret_input=secret_input,
        write=output.append,
        is_tty=lambda: True,
    )

    rendered = "".join(output)
    assert prompts == ["Base URL: ", "Model: "]
    assert secret_prompts == ["API key: ", "API key: "]
    assert "file-secret-5678" not in rendered
    assert store.read().get("api_key") == "file-secret-5678"


def test_cancelled_reconfiguration_preserves_original(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.initialize(
        base_url="https://before.invalid/v1",
        model="before-model",
        api_key="before-secret-1234",
    )
    original = store.path.read_bytes()

    with pytest.raises(KeyboardInterrupt):
        run_config_wizard(
            store,
            input_fn=lambda prompt: (_ for _ in ()).throw(KeyboardInterrupt()),
            secret_input=lambda prompt: "after-secret-5678",
            write=lambda text: None,
            is_tty=lambda: True,
        )

    assert store.path.read_bytes() == original


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, EOFError, StopIteration])
def test_cancelled_first_time_wizard_creates_no_partial_file(
    tmp_path: Path,
    error_type: type[BaseException],
) -> None:
    store = ConfigStore(tmp_path / "config.toml")

    def cancel_secret_input(prompt: str) -> str:
        raise error_type()

    with pytest.raises(error_type):
        run_config_wizard(
            store,
            input_fn=sequence_input(["https://model.invalid/v1", "demo-model"]),
            secret_input=cancel_secret_input,
            write=lambda text: None,
            is_tty=lambda: True,
        )

    assert not store.path.exists()


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, EOFError, StopIteration])
def test_final_prompt_cancellation_preserves_original_bytes(
    tmp_path: Path,
    error_type: type[BaseException],
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.initialize(
        base_url="https://before.invalid/v1",
        model="before-model",
        api_key="before-secret-1234",
    )
    original = store.path.read_bytes()

    def cancel_secret_input(prompt: str) -> str:
        raise error_type()

    with pytest.raises(error_type):
        run_config_wizard(
            store,
            input_fn=sequence_input(["https://after.invalid/v1", "after-model"]),
            secret_input=cancel_secret_input,
            write=lambda text: None,
            is_tty=lambda: True,
        )

    assert store.path.read_bytes() == original


def test_api_key_is_absent_from_output_and_persistence_error(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    output: list[str] = []
    api_key = "file-secret-\ud800-1234"

    with pytest.raises(ValueError) as error:
        run_config_wizard(
            store,
            input_fn=sequence_input(["https://model.invalid/v1", "demo-model"]),
            secret_input=lambda prompt: api_key,
            write=output.append,
            is_tty=lambda: True,
        )

    assert api_key not in "".join(output)
    assert api_key not in str(error.value)
    assert not store.path.exists()
