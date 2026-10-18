from pathlib import Path

import pytest

from baremetal_harness.config import (
    CONFIG_FIELDS,
    RUNTIME_FIELDS,
    SECRET_FIELDS,
    ConfigDocument,
    ConfigSecretProvider,
    coerce_config_value,
    default_config_path,
    default_config_values,
    resolve_config,
    validate_config_values,
)


def test_config_schema_includes_secret_without_adding_it_to_runtime_defaults() -> None:
    defaults = default_config_values()

    assert "api_key" in CONFIG_FIELDS
    assert "api_key" not in defaults
    assert defaults["model"] == "fake"
    assert isinstance(defaults["data_dir"], Path)


def test_config_schema_separates_runtime_and_secret_fields() -> None:
    assert tuple(
        field for field in CONFIG_FIELDS if field != "api_key"
    ) == RUNTIME_FIELDS
    assert frozenset({"api_key"}) == SECRET_FIELDS


def test_default_config_path_uses_current_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/baremetal_harness-home"))

    assert default_config_path() == Path("/tmp/baremetal_harness-home/.baremetal_harness/config.toml")


def test_coerce_config_value_validates_urls_and_scalar_types() -> None:
    assert coerce_config_value("base_url", "https://model.invalid/v1") == (
        "https://model.invalid/v1"
    )
    assert coerce_config_value("max_turns", "24") == 24
    assert coerce_config_value("require_strong_sandbox", "yes") is True

    with pytest.raises(ValueError, match="base_url"):
        coerce_config_value("base_url", "file:///tmp/model")
    with pytest.raises(ValueError, match="host"):
        coerce_config_value("base_url", "https:///missing-host")
    with pytest.raises(ValueError, match="api_key"):
        coerce_config_value("api_key", "   ")
    assert (
        coerce_config_value(
            "api_key",
            " file-secret-1234 ",
        )
        == " file-secret-1234 "
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://model.invalid:not-a-port/v1",
        "https://model.invalid:99999/v1",
    ],
)
def test_base_url_rejects_invalid_ports(value: str) -> None:
    with pytest.raises(ValueError, match="base_url"):
        coerce_config_value("base_url", value)


@pytest.mark.parametrize(
    "value",
    [
        "https://model.invalid:not-a-port/v1",
        "https://model.invalid:99999/v1",
    ],
)
def test_environment_base_url_rejects_invalid_ports(value: str) -> None:
    with pytest.raises(ValueError, match="base_url"):
        resolve_config(
            ConfigDocument({}),
            environ={"OPENAI_BASE_URL": value},
        )


@pytest.mark.parametrize(
    "value",
    [
        1.9,
        float("inf"),
        float("-inf"),
        float("nan"),
        True,
        False,
        "1.9",
        "1e3",
        "+1",
        "-1",
        " 1",
        "1 ",
        "01",
        "",
    ],
)
def test_integer_fields_reject_noncanonical_values(value: object) -> None:
    with pytest.raises(ValueError, match="max_turns must be a positive integer"):
        coerce_config_value("max_turns", value)


@pytest.mark.parametrize(("source", "expected"), [("1", 1), ("24", 24)])
def test_integer_fields_accept_positive_decimal_digits(
    source: str,
    expected: int,
) -> None:
    assert coerce_config_value("max_turns", source) == expected


@pytest.mark.parametrize(
    "source",
    ["1.9", "inf", "nan", "1e3", "+1", "-1", " 1", "1 ", "01"],
)
def test_environment_integer_fields_reject_noncanonical_strings(
    source: str,
) -> None:
    with pytest.raises(ValueError, match="max_turns must be a positive integer"):
        resolve_config(
            ConfigDocument({}),
            environ={"BAREMETAL_HARNESS_MAX_TURNS": source},
        )


def test_unknown_config_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown config field: unknown"):
        coerce_config_value("unknown", "value")


def test_validate_config_values_enforces_context_reserve_relationship() -> None:
    values = default_config_values()
    values["context_tokens"] = 4_000
    values["reserve_output_tokens"] = 4_000

    with pytest.raises(
        ValueError,
        match="reserve_output_tokens must be smaller than context_tokens",
    ):
        validate_config_values(values)


def test_config_document_repr_never_contains_secret() -> None:
    document = ConfigDocument({"api_key": "secret-value-1234", "model": "demo"})

    assert "secret-value-1234" not in repr(document)
    assert document.get("api_key") == "secret-value-1234"


def test_config_document_is_an_immutable_snapshot() -> None:
    values = {"model": "demo"}
    document = ConfigDocument(values)
    values["model"] = "changed"

    assert document.get("model") == "demo"
    with pytest.raises(TypeError):
        document.values["model"] = "changed"  # type: ignore[index]


def test_resolve_config_applies_defaults_document_environment_then_cli() -> None:
    document = ConfigDocument(
        {
            "workspace": Path("/from-file"),
            "model": "file-model",
            "base_url": "https://file.invalid/v1",
            "max_turns": 4,
            "api_key": "file-secret-1234",
        }
    )

    config = resolve_config(
        document,
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


def test_environment_secret_overrides_file_secret() -> None:
    provider = ConfigSecretProvider(
        ConfigDocument({"api_key": "file-secret-1234"}),
        {"OPENAI_API_KEY": " environment-secret-5678 "},
    )

    assert provider.get("OPENAI_API_KEY") == " environment-secret-5678 "
    assert provider.get("UNKNOWN_SECRET") is None


def test_whitespace_only_environment_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="api_key"):
        ConfigSecretProvider(
            ConfigDocument({"api_key": "file-secret-1234"}),
            {"OPENAI_API_KEY": "   "},
        )


def test_file_secret_is_used_when_environment_is_empty() -> None:
    provider = ConfigSecretProvider(
        ConfigDocument({"api_key": "file-secret-1234"}),
        {"OPENAI_API_KEY": ""},
    )

    assert provider.get("OPENAI_API_KEY") == "file-secret-1234"
