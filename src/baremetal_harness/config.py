import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

CONFIG_FIELDS = (
    "data_dir",
    "workspace",
    "model",
    "base_url",
    "api_key",
    "require_strong_sandbox",
    "docker_image",
    "max_turns",
    "max_tool_calls",
    "context_tokens",
    "reserve_output_tokens",
)
RUNTIME_FIELDS = tuple(field for field in CONFIG_FIELDS if field != "api_key")
SECRET_FIELDS = frozenset({"api_key"})


@dataclass(frozen=True, slots=True)
class BareMetalHarnessConfig:
    data_dir: Path
    workspace: Path
    model: str = "fake"
    base_url: str | None = None
    require_strong_sandbox: bool = False
    docker_image: str = "python:3.12-slim"
    max_turns: int = 16
    max_tool_calls: int = 32
    context_tokens: int = 32_000
    reserve_output_tokens: int = 4_000


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class EnvironmentSecretProvider:
    def get(self, name: str) -> str | None:
        return os.environ.get(name)


def default_config_path() -> Path:
    return Path.home() / ".baremetal_harness" / "config.toml"


def default_config_values() -> dict[str, object]:
    return {
        "data_dir": Path.home() / ".baremetal_harness",
        "workspace": Path.cwd(),
        "model": "fake",
        "base_url": None,
        "require_strong_sandbox": False,
        "docker_image": "python:3.12-slim",
        "max_turns": 16,
        "max_tool_calls": 32,
        "context_tokens": 32_000,
        "reserve_output_tokens": 4_000,
    }


_ENVIRONMENT_FIELDS = {
    "BAREMETAL_HARNESS_DATA_DIR": "data_dir",
    "BAREMETAL_HARNESS_WORKSPACE": "workspace",
    "OPENAI_MODEL": "model",
    "OPENAI_BASE_URL": "base_url",
    "BAREMETAL_HARNESS_REQUIRE_STRONG_SANDBOX": "require_strong_sandbox",
    "BAREMETAL_HARNESS_DOCKER_IMAGE": "docker_image",
    "BAREMETAL_HARNESS_MAX_TURNS": "max_turns",
    "BAREMETAL_HARNESS_MAX_TOOL_CALLS": "max_tool_calls",
    "BAREMETAL_HARNESS_CONTEXT_TOKENS": "context_tokens",
    "BAREMETAL_HARNESS_RESERVE_OUTPUT_TOKENS": "reserve_output_tokens",
}

_PATH_FIELDS = {"data_dir", "workspace"}
INTEGER_CONFIG_FIELDS = (
    "max_turns",
    "max_tool_calls",
    "context_tokens",
    "reserve_output_tokens",
)


def coerce_config_value(field: str, value: object) -> object:
    if field not in CONFIG_FIELDS:
        raise ValueError(f"unknown config field: {field}")
    if field in _PATH_FIELDS:
        if not isinstance(value, (str, Path)):
            raise ValueError(f"{field} must be a path")
        return Path(value).expanduser()
    if field in INTEGER_CONFIG_FIELDS:
        if type(value) is int:
            converted = value
        elif (
            isinstance(value, str)
            and value.isascii()
            and value.isdecimal()
            and value[0] != "0"
        ):
            converted = int(value)
        else:
            raise ValueError(f"{field} must be a positive integer")
        if converted <= 0:
            raise ValueError(f"{field} must be a positive integer")
        return converted
    if field == "require_strong_sandbox":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError(f"{field} must be a boolean")
    if field == "base_url":
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("base_url must be an HTTP(S) URL")
        normalized = value.strip()
        try:
            parsed = urlsplit(normalized)
            # urlsplit defers port validation until the attribute is read.
            _ = parsed.port
        except ValueError as error:
            raise ValueError("base_url must include a valid port") from error
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("base_url must use http or https")
        if not parsed.hostname:
            raise ValueError("base_url must include a host")
        return normalized
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if field == "api_key":
        return value
    return value.strip()


def validate_config_values(values: Mapping[str, object]) -> None:
    unknown = set(values) - set(CONFIG_FIELDS)
    if unknown:
        raise ValueError(f"unknown config fields: {sorted(unknown)}")
    converted = {
        field: coerce_config_value(field, value) for field, value in values.items()
    }
    context_tokens = converted.get("context_tokens")
    reserve = converted.get("reserve_output_tokens")
    if (
        context_tokens is not None
        and reserve is not None
        and int(reserve) >= int(context_tokens)
    ):
        raise ValueError("reserve_output_tokens must be smaller than context_tokens")


@dataclass(frozen=True, slots=True, repr=False)
class ConfigDocument:
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        snapshot = dict(self.values)
        validate_config_values(snapshot)
        object.__setattr__(self, "values", MappingProxyType(snapshot))

    def get(self, field: str) -> object | None:
        if field not in CONFIG_FIELDS:
            raise ValueError(f"unknown config field: {field}")
        return self.values.get(field)


class ConfigSecretProvider:
    def __init__(
        self,
        document: ConfigDocument,
        environ: Mapping[str, str],
    ) -> None:
        self._api_key = document.get("api_key")
        environment_api_key = environ.get("OPENAI_API_KEY")
        self._environment_api_key = (
            coerce_config_value("api_key", environment_api_key)
            if environment_api_key
            else environment_api_key
        )

    def get(self, name: str) -> str | None:
        if name != "OPENAI_API_KEY":
            return None
        if self._environment_api_key:
            return self._environment_api_key
        return str(self._api_key) if self._api_key is not None else None


def resolve_config(
    document: ConfigDocument,
    *,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> BareMetalHarnessConfig:
    values = default_config_values()
    values.update(
        {
            field: value
            for field, value in document.values.items()
            if field in RUNTIME_FIELDS
        }
    )

    environment = os.environ if environ is None else environ
    for variable, field in _ENVIRONMENT_FIELDS.items():
        value = environment.get(variable)
        if value:
            values[field] = coerce_config_value(field, value)

    if overrides is not None:
        unknown = set(overrides) - set(RUNTIME_FIELDS)
        if unknown:
            raise ValueError(f"unknown config overrides: {sorted(unknown)}")
        for field, value in overrides.items():
            if value is not None:
                values[field] = coerce_config_value(field, value)

    validate_config_values(values)
    return BareMetalHarnessConfig(**values)


def load_config(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> BareMetalHarnessConfig:
    from baremetal_harness.config_store import ConfigStore

    document = ConfigStore(path).read()
    return resolve_config(document, environ=environ, overrides=overrides)
